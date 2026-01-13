from __future__ import annotations
import os
import json
import time
import warnings
import pandas as pd
from collections import namedtuple
from enum import Enum
from datetime import datetime
from pathlib import Path
import glob
from typing import Optional, Literal, Union

# 3rd party
import pyotp

from selenium import webdriver
from selenium.webdriver.chrome.service import Service as ChromeService
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support.ui import Select, WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import (
    NoSuchElementException,
    WebDriverException,
    StaleElementReferenceException,
    ElementClickInterceptedException,
    ElementNotInteractableException,
    TimeoutException,
)
from webdriver_manager.chrome import ChromeDriverManager
from termcolor import colored

# Constants
DEFAULT_TZ_HOME_URL = 'https://standard.tradezeroweb.us/'

class Order(Enum):
    BUY = 'buy'
    SELL = 'sell'
    SHORT = 'short'
    COVER = 'cover'

class TIF(Enum):
    DAY = 'DAY'
    GTC = 'GTC'
    GTX = 'GTX'

class TradeZero:
    def __init__(self, user_name: str, password: str, headless: bool = False, home_url: Optional[str] = None, mfa_secret: Optional[str] = None):
        self.user_name = user_name
        self.password = password
        # Allow arg override, else fallback to env
        self.mfa_secret = (mfa_secret or os.getenv("TRADEZERO_MFA_SECRET") or "").strip()
        self.home_url = (home_url or DEFAULT_TZ_HOME_URL).strip()
        
        def _find_cached_chromedriver() -> str | None:
            # 1) Explicit override
            for env_key in ("TRADEZERO_CHROMEDRIVER_PATH", "CHROMEDRIVER_PATH"):
                p = (os.getenv(env_key) or "").strip().strip('"')
                if p and os.path.exists(p):
                    return p

            # 2) webdriver_manager cache (works offline)
            userprofile = (os.getenv("USERPROFILE") or "").strip()
            if userprofile:
                base = Path(userprofile) / ".wdm" / "drivers" / "chromedriver"
                if base.exists():
                    hits = glob.glob(str(base / "**" / "chromedriver.exe"), recursive=True)
                    if hits:
                        hits.sort(key=lambda x: os.path.getmtime(x), reverse=True)
                        return hits[0]
            return None

        cached = _find_cached_chromedriver()
        if cached:
            service = ChromeService(cached)
        else:
            service = ChromeService(ChromeDriverManager().install())
        options = webdriver.ChromeOptions()
        options.add_experimental_option('excludeSwitches', ['enable-logging'])
        if headless:
            options.add_argument('--headless')
            options.add_argument('--disable-gpu')
        
        self.driver = webdriver.Chrome(service=service, options=options)
        self.driver.get(self.home_url)

        # Debug: when enabled, write DOM/CSS snapshots to repo-root logs/.
        self._debug_dump_dom = (os.getenv("TZ_DEBUG_DUMP", "0").strip().lower() in {"1", "true", "yes"})
        
        # Initial login
        self.login()

    def _repo_root(self) -> Path:
        """Return repository root.

        Avoid relying on a fixed parent depth because this repo often lives inside
        deeper directory structures on Windows.
        """

        here = Path(__file__).resolve()

        # Heuristic: walk upwards until we find a marker file that exists at the
        # repo root in this project.
        markers = ["docker-compose.yml", "requirements.txt", "README.md"]
        for parent in [here.parent, *here.parents]:
            try:
                if any((parent / m).exists() for m in markers) and (parent / "prod").exists():
                    return parent
            except Exception:
                # In rare cases on Windows, probing some paths can throw.
                continue

        # Fallback: assume the historical layout .../prod/backend/execution/tradezero/client.py
        # and go up to the workspace root.
        return here.parents[4]

    def _logs_dir(self) -> Path:
        return self._repo_root() / "logs"

    def _wait_document_ready(self, timeout_s: float = 30.0) -> bool:
        """Wait for document.readyState == 'complete' (best-effort)."""
        try:
            WebDriverWait(self.driver, timeout_s).until(
                lambda d: (d.execute_script("return document.readyState") or "").lower() == "complete"
            )
            return True
        except Exception:
            return False

    def _dom_fully_loaded(self, iter_amount: int = 1):
        """Check that webpage elements are fully loaded/visible."""
        container_xpath = "//*[contains(@id,'portfolio-container')]//div//div//h2"
        for i in range(iter_amount):
            try:
                elements = self.driver.find_elements(By.XPATH, container_xpath)
                text_elements = [x.text for x in elements]
                if 'Portfolio' in text_elements:
                    return True
            except:
                pass
            time.sleep(0.5)
        return False

    def _wait_for_any(self, candidates: list[tuple[str, str]], timeout_s: float = 20.0):
        """Return the first element found from a list of (by, value) locators."""
        last_exc: Optional[Exception] = None
        end = time.time() + timeout_s
        while time.time() < end:
            for by, value in candidates:
                try:
                    el = self.driver.find_element(by, value)
                    if el:
                        return el
                except Exception as e:
                    last_exc = e
                    continue
            time.sleep(0.2)
        if last_exc:
            raise last_exc
        raise TimeoutException("Timed out waiting for any candidate element")

    def _wait_for_trading_panel_ready(self, timeout_s: float = 45.0) -> bool:
        """Wait until the trading ticket UI is usable after login/navigation."""
        try:
            self._wait_document_ready(timeout_s=min(timeout_s, 20.0))
            WebDriverWait(self.driver, timeout_s).until(
                EC.presence_of_element_located((By.ID, "trading-order-select-type"))
            )
            WebDriverWait(self.driver, timeout_s).until(
                EC.presence_of_element_located((By.ID, "trading-order-input-symbol"))
            )
            return True
        except Exception:
            return False

    def _dump_ui_snapshot(self, reason: str) -> None:
        """Write HTML + best-effort CSS + diagnostics for selector debugging.

        Files are written under repo-root logs/ as tradezero_ui_<timestamp>_<reason>/*
        """
        if not self._debug_dump_dom:
            return

        try:
            ts = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
            safe_reason = "".join(ch if ch.isalnum() or ch in {"-", "_"} else "_" for ch in (reason or "snapshot"))
            out_dir = self._logs_dir() / f"tradezero_ui_{ts}_{safe_reason}"
            out_dir.mkdir(parents=True, exist_ok=True)

            meta = {
                "timestamp_utc": ts,
                "reason": reason,
                "url": getattr(self.driver, "current_url", ""),
                "ready_state": None,
            }
            try:
                meta["ready_state"] = self.driver.execute_script("return document.readyState")
            except Exception:
                pass

            # HTML
            try:
                (out_dir / "page.html").write_text(self.driver.page_source or "", encoding="utf-8", errors="ignore")
            except Exception:
                pass

            # Screenshot
            try:
                self.driver.save_screenshot(str(out_dir / "page.png"))
            except Exception:
                pass

            # Useful diagnostics (IDs and dropdown options).
            diag: dict[str, object] = {}
            for eid in [
                "trading-order-select-type",
                "trading-order-input-symbol",
                "portfolio-tab-ao-1",
                "portfolio-tab-op-1",
                "aoTable-1",
                "opTable-1",
            ]:
                try:
                    el = self.driver.find_element(By.ID, eid)
                    diag[eid] = {
                        "tag": el.tag_name,
                        "displayed": bool(el.is_displayed()),
                        "enabled": bool(el.is_enabled()),
                    }
                except Exception as e:
                    diag[eid] = {"error": str(e)}

            try:
                sel = Select(self.driver.find_element(By.ID, "trading-order-select-type"))
                diag["order_type_options"] = [((o.text or "").strip()) for o in sel.options]
            except Exception as e:
                diag["order_type_options"] = {"error": str(e)}

            # Best-effort CSS extraction. This can fail due to cross-origin stylesheet restrictions.
            css_text = ""
            try:
                css_text = self.driver.execute_script(
                    """
                    const out = [];
                    // Inline <style> tags
                    document.querySelectorAll('style').forEach(s => out.push(s.textContent || ''));
                    // Same-origin stylesheets (cssRules access can throw)
                    for (const ss of document.styleSheets) {
                      try {
                        const rules = ss.cssRules;
                        if (!rules) continue;
                        let txt = '';
                        for (const r of rules) { txt += r.cssText + '\n'; }
                        if (txt.trim()) out.push(txt);
                      } catch (e) {
                        // ignore
                      }
                    }
                    return out.join('\n\n/* ---- */\n\n');
                    """
                ) or ""
            except Exception:
                css_text = ""

            try:
                (out_dir / "styles.css").write_text(css_text, encoding="utf-8", errors="ignore")
            except Exception:
                pass

            try:
                (out_dir / "meta.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")
                (out_dir / "diagnostics.json").write_text(json.dumps(diag, indent=2), encoding="utf-8")
            except Exception:
                pass

            print(f"TZ DEBUG: UI snapshot saved to {out_dir}")
        except Exception:
            # Never allow debug dumping to break trading.
            return

    def _dismiss_modal_overlays(self) -> None:
        """Best-effort close of modal overlays that block clicks (simplemodal)."""
        try:
            # If this is an order confirmation modal, we must confirm (not dismiss).
            if self._handle_order_confirmation_modal():
                return

            overlays = self.driver.find_elements(By.CSS_SELECTOR, "div.simplemodal-overlay")
            if overlays:
                # Try clicking the overlay itself (some modals close on overlay click)
                try:
                    overlays[0].click()
                    time.sleep(0.2)
                except Exception:
                    pass

                # Try close buttons first
                for sel in [
                    "a.simplemodal-close",
                    "button.simplemodal-close",
                    ".simplemodal-close",
                    "#simplemodal-container a.close",
                ]:
                    try:
                        btn = self.driver.find_element(By.CSS_SELECTOR, sel)
                        btn.click()
                        time.sleep(0.2)
                        return
                    except Exception:
                        continue

                # Try common buttons inside the modal container
                for xp in [
                    "//div[@id='simplemodal-container']//button[contains(translate(., 'OKCLOSE', 'okclose'), 'ok') or contains(translate(., 'OKCLOSE', 'okclose'), 'close')]",
                    "//div[@id='simplemodal-container']//a[contains(translate(., 'OKCLOSE', 'okclose'), 'ok') or contains(translate(., 'OKCLOSE', 'okclose'), 'close')]",
                ]:
                    try:
                        btn = self.driver.find_element(By.XPATH, xp)
                        btn.click()
                        time.sleep(0.2)
                        return
                    except Exception:
                        continue

                # Fallback: ESC key to dismiss
                try:
                    self.driver.find_element(By.TAG_NAME, "body").send_keys(Keys.ESCAPE)
                    time.sleep(0.2)
                except Exception:
                    pass

                # Last resort: remove overlay + container via JS (prevents click-intercept deadlocks)
                try:
                    self.driver.execute_script(
                        "document.querySelectorAll('.simplemodal-overlay, #simplemodal-container, #simplemodal-data')"
                        ".forEach(e => e && e.remove && e.remove());"
                    )
                    time.sleep(0.1)
                except Exception:
                    pass
        except Exception:
            pass

    def _handle_order_confirmation_modal(self) -> bool:
        """If an 'Order Confirmation' modal is present, click Confirm.
        
        Also handles 'Short locate' warnings (Hard to Borrow) by canceling them to verify order failure.

        Returns True if it handled a confirmation modal (SUCCESS).
        Returns False if no modal or handled a FAILURE modal (Short Locate / Error).
        """
        try:
            container = self.driver.find_elements(By.CSS_SELECTOR, "#simplemodal-container")
            if not container:
                return False

            text = (container[0].text or "").lower()
            
            # --- CASE 1: Short Locate Warning (cancel to clear UI, report failure) ---
            if "short locate" in text or "hard to borrow" in text:
                print("Detected 'Hard to Borrow/Locate Required' modal - Canceling order.")
                try:
                    # Click Cancel
                    cancel_btn = self.driver.find_element(By.ID, "short-locate-button-cancel")
                    cancel_btn.click()
                except:
                    # Fallback generic cancel
                    self._dismiss_modal_overlays()
                
                # Wait for modal to disappear to prevent blocking next actions
                time.sleep(2.0)
                try:
                    WebDriverWait(self.driver, 3).until(
                        EC.invisibility_of_element_located((By.ID, "simplemodal-container"))
                    )
                except Exception:
                    pass
                    
                return False # Order failed

            # --- CASE 2: Order Confirmation (Confirm to proceed) ---
            if "order confirmation" not in text:
                return False

            # Try to tick "Disable this confirmation window" to reduce future friction.
            # This is best-effort; we still confirm even if we can't tick it.
            try:
                # Prefer clicking the actual checkbox input if available.
                checkbox = None
                for xp in [
                    "//div[@id='simplemodal-container']//input[@type='checkbox' and (contains(@id,'disable') or contains(@name,'disable'))]",
                    "//div[@id='simplemodal-container']//*[contains(translate(., 'DISABLETHISCONFIRMATIONWINDOW', 'disablethisconfirmationwindow'), 'disable this confirmation')]/ancestor::*[self::label or self::div][1]//input[@type='checkbox']",
                    "//div[@id='simplemodal-container']//*[contains(translate(., 'DISABLETHISCONFIRMATIONWINDOW', 'disablethisconfirmationwindow'), 'disable this confirmation')]/preceding::input[@type='checkbox'][1]",
                ]:
                    try:
                        checkbox = self.driver.find_element(By.XPATH, xp)
                        break
                    except Exception:
                        continue

                if checkbox is not None:
                    try:
                        selected = bool(checkbox.is_selected())
                    except Exception:
                        selected = bool(checkbox.get_attribute("checked"))

                    if not selected:
                        try:
                            checkbox.click()
                        except Exception:
                            self.driver.execute_script("arguments[0].click();", checkbox)
                        time.sleep(0.1)
                else:
                    # Fall back to clicking the label/text itself.
                    disable_label = self.driver.find_element(
                        By.XPATH,
                        "//div[@id='simplemodal-container']//*[contains(translate(., 'DISABLETHISCONFIRMATIONWINDOW', 'disablethisconfirmationwindow'), 'disable this confirmation')]",
                    )
                    try:
                        disable_label.click()
                    except Exception:
                        self.driver.execute_script("arguments[0].click();", disable_label)
                    time.sleep(0.1)
            except Exception:
                pass

            # Click Confirm button/link
            for xp in [
                "//div[@id='simplemodal-container']//button[normalize-space()='Confirm']",
                "//div[@id='simplemodal-container']//a[normalize-space()='Confirm']",
                "//div[@id='simplemodal-container']//*[self::button or self::a or self::span][contains(translate(normalize-space(.), 'CONFIRM', 'confirm'), 'confirm') and not(contains(translate(normalize-space(.), 'CANCEL', 'cancel'), 'cancel'))]",
            ]:
                try:
                    el = self.driver.find_element(By.XPATH, xp)
                    try:
                        el.click()
                    except Exception:
                        self.driver.execute_script("arguments[0].click();", el)
                    time.sleep(0.3)
                    return True
                except Exception:
                    continue

            return False
        except Exception:
            return False

    def _safe_click(self, by: By, selector: str, retries: int = 1) -> None:
        last_err: Exception | None = None
        for _ in range(max(1, retries + 1)):
            try:
                self._dismiss_modal_overlays()
                el = WebDriverWait(self.driver, 10).until(
                    EC.presence_of_element_located((by, selector))
                )

                # Scroll into view; TradeZero often renders tabs off-screen.
                try:
                    self.driver.execute_script(
                        "arguments[0].scrollIntoView({block: 'center', inline: 'center'});",
                        el,
                    )
                    time.sleep(0.1)
                except Exception:
                    pass

                # Prefer a real click when possible.
                try:
                    WebDriverWait(self.driver, 5).until(
                        EC.element_to_be_clickable((by, selector))
                    )
                    el.click()
                except (TimeoutException, ElementClickInterceptedException, ElementNotInteractableException):
                    # Fallback: JS click bypasses hit-testing/overlay issues.
                    self._dismiss_modal_overlays()
                    self.driver.execute_script("arguments[0].click();", el)
                return
            except ElementClickInterceptedException as e:
                last_err = e
                self._dismiss_modal_overlays()
                time.sleep(0.25)
                # Try JS click as a fallback (bypasses hit-testing)
                try:
                    el = self.driver.find_element(by, selector)
                    self.driver.execute_script("arguments[0].click();", el)
                    return
                except Exception:
                    pass
            except ElementNotInteractableException as e:
                last_err = e
                self._dismiss_modal_overlays()
                time.sleep(0.25)
                try:
                    el = self.driver.find_element(by, selector)
                    self.driver.execute_script("arguments[0].click();", el)
                    return
                except Exception:
                    pass
            except Exception as e:
                last_err = e
                break
        if last_err:
            raise last_err

    def login(self):
        """Log in to TradeZero."""
        print("Logging in...")
        try:
            # TradeZero portals differ. Try the standard IDs first, then fall back to common patterns.
            try:
                login_form = self.driver.find_element(By.ID, "login")
            except Exception:
                login_form = None

            if login_form is None:
                # Common alternates: email/username fields
                for selector in [
                    (By.CSS_SELECTOR, "input[type='email']"),
                    (By.CSS_SELECTOR, "input[name='email']"),
                    (By.CSS_SELECTOR, "input[name='username']"),
                    (By.CSS_SELECTOR, "input[id*='user']"),
                ]:
                    try:
                        login_form = self.driver.find_element(*selector)
                        break
                    except Exception:
                        continue

            if login_form is None:
                raise RuntimeError(
                    f"Could not find username/email input. Current URL: {self.driver.current_url}"
                )

            login_form.clear()
            login_form.send_keys(self.user_name)

            try:
                password_form = self.driver.find_element(By.ID, "password")
            except Exception:
                password_form = None

            if password_form is None:
                for selector in [
                    (By.CSS_SELECTOR, "input[type='password']"),
                    (By.CSS_SELECTOR, "input[name='password']"),
                ]:
                    try:
                        password_form = self.driver.find_element(*selector)
                        break
                    except Exception:
                        continue

            if password_form is None:
                raise RuntimeError(
                    f"Could not find password input. Current URL: {self.driver.current_url}"
                )

            password_form.clear()
            password_form.send_keys(self.password, Keys.RETURN)
            
            # --- MFA Handling ---
            if self.mfa_secret:
                print("Checking for MFA challenge...")
                
                # Wait for page transition (url change or password field gone)
                # But simple sleep + retry is surprisingly robust for redirects
                mfa_input = None
                
                # Try finding MFA input for up to 10 seconds
                start_search = time.time()
                while time.time() - start_search < 10.0:
                    for selector in [
                        (By.ID, "code2fa"),      # Found in logs (Step 2: Multi-Factor Authentication)
                        (By.NAME, "code2fa"),
                        (By.NAME, "code"),
                        (By.NAME, "otp"),
                        (By.NAME, "totp"),
                        (By.ID, "totp"),
                        (By.CSS_SELECTOR, "input[autocomplete='one-time-code']"),
                        (By.CSS_SELECTOR, "input[placeholder*='code']"),
                        (By.CSS_SELECTOR, "input[type='tel']"),
                        (By.CSS_SELECTOR, "input.two-factor-input"),
                    ]:
                        try:
                            els = self.driver.find_elements(*selector)
                            for el in els:
                                if el.is_displayed():
                                    mfa_input = el
                                    break
                            if mfa_input: break
                        except: continue
                    
                    if mfa_input:
                        break
                    time.sleep(1.0)

                if mfa_input:
                    print(f"MFA Input found: {mfa_input.get_attribute('name') or mfa_input.get_attribute('id')}")
                    
                    # Try to check "Remember this device"
                    try:
                        remember_cb = self.driver.find_element(By.ID, "skipMFA")
                        if remember_cb.is_displayed() and not remember_cb.is_selected():
                            print("Checking 'Remember this device'...")
                            # Try clicking the input directly first
                            try:
                                remember_cb.click()
                            except:
                                # Fallback to clicking parent/label if input handles weirdly
                                self.driver.execute_script("arguments[0].click();", remember_cb)
                    except Exception as e:
                        # Non-critical
                        pass

                    totp = pyotp.TOTP(self.mfa_secret.replace(" ", ""))
                    code = totp.now()
                    print(f"Submitting MFA Code: {code}")
                    
                    try:
                        mfa_input.clear()
                        mfa_input.send_keys(code)
                        mfa_input.send_keys(Keys.RETURN)
                        time.sleep(1.0) # Wait for submission
                        
                        # Handle potential "Verify" button if Enter didn't work
                        # The log shows <input type="submit" name="validate" value="Submit">
                        try:
                            # Try standard buttons first
                            verify_btns = self.driver.find_elements(By.XPATH, "//button[contains(translate(., 'VERIFY', 'verify'), 'verify') or contains(translate(., 'SUBMIT', 'submit'), 'submit')]")
                            # Try input submit buttons
                            verify_btns.extend(self.driver.find_elements(By.XPATH, "//input[@type='submit']"))
                            
                            for btn in verify_btns:
                                if btn.is_displayed():
                                    btn.click()
                                    break
                        except: pass
                        
                    except Exception as e:
                        print(f"MFA Submission error: {e}")
                else:
                    print(f"No MFA input found after 10s wait. URL: {self.driver.current_url}")
                    self._dump_ui_snapshot("mfa_not_found")

            # Prefer waiting for the trading panel to appear over a brittle 'Portfolio' header check.
            if self._wait_for_trading_panel_ready(timeout_s=60) or self._dom_fully_loaded(60):
                print("Login successful.")
                self._dump_ui_snapshot("after_login")
                # Best-effort: set default order type to Limit.
                try:
                    Select(self.driver.find_element(By.ID, "trading-order-select-type")).select_by_index(1)
                except Exception:
                    pass
            else:
                err = self._try_get_login_error_text()
                if err:
                    print(f"Login failed: {err}")
                else:
                    print("Login might have failed or timed out (trading panel not ready).")
                self._dump_ui_snapshot("login_not_ready")
        except Exception as e:
            print(f"Login error: {e}")
            self._dump_ui_snapshot("login_exception")

    def _try_get_login_error_text(self) -> str:
        """Best-effort extraction of a human-readable login error from the current page."""
        xpaths = [
            "//*[contains(translate(normalize-space(.), 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), 'identity service')]",
            "//*[contains(translate(normalize-space(.), 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), 'identity')]",
            "//*[contains(translate(normalize-space(.), 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), 'invalid')]",
            "//*[contains(@class, 'alert') and string-length(normalize-space(.)) > 0]",
            "//*[contains(@class, 'error') and string-length(normalize-space(.)) > 0]",
            "//*[contains(@id, 'error') and string-length(normalize-space(.)) > 0]",
        ]

        for xp in xpaths:
            try:
                elems = self.driver.find_elements(By.XPATH, xp)
                for el in elems:
                    txt = (el.text or "").strip()
                    if txt:
                        # Keep it short to avoid dumping the whole page.
                        return " ".join(txt.split())[:300]
            except Exception:
                continue

        return ""

    def exit(self):
        """Close Selenium window and driver."""
        try:
            self.driver.close()
        except:
            pass
        self.driver.quit()

    def current_symbol(self):
        """Get current symbol in the trading window."""
        try:
            return self.driver.find_element(By.ID, 'trading-order-symbol').text.replace('(USD)', '').strip()
        except:
            return ""

    def load_symbol(self, symbol: str):
        """Ensure the symbol is loaded in the trading window."""
        symbol = symbol.upper()
        if symbol == self.current_symbol():
            # Check if price is valid
            try:
                price = self.driver.find_element(By.ID, "trading-order-ask").text.replace('.', '').replace(',', '')
                if price.isdigit() and float(price) > 0:
                    return True
            except:
                pass

        try:
            if not self._wait_for_trading_panel_ready(timeout_s=20):
                print("Warning: Trading panel not ready; attempting symbol load anyway.")

            input_symbol = self.driver.find_element(By.ID, "trading-order-input-symbol")
            input_symbol.clear()
            input_symbol.send_keys(symbol, Keys.RETURN)

            def _ask_is_valid_or_modal_handled(_driver) -> bool:
                # Check for blocking modal first
                try:
                    modals = _driver.find_elements(By.CSS_SELECTOR, "#simplemodal-container")
                    if modals and modals[0].is_displayed():
                        text = modals[0].text.lower()
                        if "short locate" in text or "hard to borrow" in text:
                            print("DEBUG: 'Hard to Borrow' modal appeared during load_symbol. Canceling.")
                            try:
                                _driver.find_element(By.ID, "short-locate-button-cancel").click()
                                time.sleep(0.5)
                            except:
                                pass
                except Exception:
                    pass

                try:
                    price_text = _driver.find_element(By.ID, "trading-order-ask").text.replace(",", "")
                    return bool(price_text) and price_text.replace(".", "").isdigit() and float(price_text) > 0
                except Exception:
                    return False

            try:
                # Increased timeout to 25s for slow load/modals clearing
                WebDriverWait(self.driver, 25).until(_ask_is_valid_or_modal_handled)
                return True
            except TimeoutException:
                print(f"Warning: Could not load symbol {symbol} (ask did not populate within 25s)")
                self._dump_ui_snapshot(f"load_symbol_timeout_{symbol}")
                return False
        except Exception as e:
            print(f"Error loading symbol {symbol}: {e}")
            self._dump_ui_snapshot(f"load_symbol_exception_{symbol}")
            return False

    @property
    def bid(self):
        return float(self.driver.find_element(By.ID, 'trading-order-bid').text.replace(',', ''))

    @property
    def ask(self):
        return float(self.driver.find_element(By.ID, 'trading-order-ask').text.replace(',', ''))

    @property
    def last(self):
        return float(self.driver.find_element(By.ID, 'trading-order-p').text.replace(',', ''))

    def get_market_data(self, symbol: str):
        """Return market data for a symbol."""
        Data = namedtuple('Data', ['open', 'high', 'low', 'close', 'volume', 'last', 'ask', 'bid'])
        if not self.load_symbol(symbol):
            return None
        
        try:
            element_ids = [
                'trading-order-open', 'trading-order-high', 'trading-order-low', 
                'trading-order-close', 'trading-order-vol', 'trading-order-p', 
                'trading-order-ask', 'trading-order-bid'
            ]
            values = []
            for eid in element_ids:
                val = self.driver.find_element(By.ID, eid).text.replace(',', '')
                values.append(float(val) if val else 0.0)
            return Data._make(values)
        except Exception as e:
            print(f"Error getting data for {symbol}: {e}")
            return None

    def locate_stock(self, symbol: str, share_amount: int, max_price: float = 0.05, debug: bool = True):
        """
        Locate shares for shorting.
        :param max_price: Max price per share you are willing to pay for the locate.
        """
        Data = namedtuple('Data', ['price_per_share', 'total', 'status'])
        
        if share_amount % 100 != 0:
            raise ValueError(f"Share amount must be divisible by 100 (got {share_amount})")

        if not self.load_symbol(symbol):
            return Data(0, 0, 'error')

        try:
            # Click Locate Tab
            clicked = False
            for loc in [
                (By.ID, "locate-tab-1"),
                (By.CSS_SELECTOR, "[id^='locate-tab-']"),
                (By.XPATH, "//a[contains(translate(., 'LOCATE', 'locate'), 'locate')]"),
            ]:
                try:
                    self._safe_click(loc[0], loc[1], retries=1)
                    clicked = True
                    break
                except Exception:
                    continue

            if not clicked:
                # Some TradeZero portal variants (notably paper) don't expose locates in the UI.
                # In that case, treat locate as "not available" and let the short submission decide.
                raise NoSuchElementException(
                    "Locate tab not found (locate-tab-1 / locate-tab-* / link text)"
                )
            
            # Input Symbol
            input_symbol = self.driver.find_element(By.ID, "short-list-input-symbol")
            input_symbol.clear()
            input_symbol.send_keys(symbol, Keys.RETURN)
            
            # Input Shares
            input_shares = self.driver.find_element(By.ID, "short-list-input-shares")
            input_shares.clear()
            input_shares.send_keys(share_amount)
            
            # Wait for status
            time.sleep(0.5)
            status_elem = self.driver.find_element(By.ID, "short-list-locate-status")
            
            # Wait for status to populate
            for _ in range(20):
                if status_elem.text:
                    break
                time.sleep(0.1)

            if status_elem.text == 'Easy to borrow':
                if debug: print(f"{symbol} is Easy to Borrow (Free)")
                return Data(0.0, 0.0, 'success')

            # Hard to Borrow - Click Locate
            self._safe_click(By.ID, "short-list-button-locate", retries=1)
            
            # Wait for result
            locate_pps = 0.0
            locate_total = 0.0
            
            for i in range(50):
                try:
                    # Try to find the result row
                    pps_elem = self.driver.find_element(By.ID, f"oitem-l-{symbol.upper()}-cell-2")
                    total_elem = self.driver.find_element(By.ID, f"oitem-l-{symbol.upper()}-cell-6")
                    locate_pps = float(pps_elem.text)
                    locate_total = float(total_elem.text)
                    break
                except:
                    time.sleep(0.1)
            else:
                print("Timeout waiting for locate response")
                return Data(0, 0, 'timeout')

            if debug: print(f"Locate found: {share_amount} shares @ ${locate_pps}/share (Total: ${locate_total})")

            if locate_pps <= max_price:
                # Accept
                self.driver.find_element(By.XPATH, f'//*[@id="oitem-l-{symbol.upper()}-cell-8"]/span[1]').click()
                if debug: print("Locate ACCEPTED")
                return Data(locate_pps, locate_total, 'success')
            else:
                # Decline
                self.driver.find_element(By.XPATH, f'//*[@id="oitem-l-{symbol.upper()}-cell-8"]/span[2]').click()
                if debug: print(f"Locate DECLINED (Price ${locate_pps} > Max ${max_price})")
                return Data(locate_pps, locate_total, 'declined')

        except NoSuchElementException as e:
            if debug:
                print(f"Locate UI not available for {symbol}: {e}")
            return Data(0, 0, 'not_available')
        except Exception as e:
            print(f"Error locating {symbol}: {e}")
            return Data(0, 0, 'error')

    def limit_order(self, direction: Order, symbol: str, quantity: int, price: float, tif: TIF = TIF.DAY):
        """Place a Limit Order."""
        try:
            self.load_symbol(symbol)
            
            # Select Limit Order (Index 1)
            Select(self.driver.find_element(By.ID, "trading-order-select-type")).select_by_index(1)
            
            # Select TIF
            Select(self.driver.find_element(By.ID, "trading-order-select-time")).select_by_visible_text(tif.value)
            
            # Quantity
            qty_input = self.driver.find_element(By.ID, "trading-order-input-quantity")
            qty_input.clear()
            qty_input.send_keys(quantity)
            
            # Price
            price_input = self.driver.find_element(By.ID, "trading-order-input-price")
            price_input.clear()
            price_input.send_keys(str(price))
            
            # Click Button
            btn_id = f"trading-order-button-{direction.value}"
            self._safe_click(By.ID, btn_id, retries=1)

            # Many portals show a confirmation modal after submission.
            self._handle_order_confirmation_modal()
            
            print(f"Placed LIMIT {direction.value.upper()} {quantity} {symbol} @ {price}")
            return True
        except Exception as e:
            print(f"Error placing limit order: {e}")
            return False

    def stop_order(self, direction: Order, symbol: str, quantity: int, stop_price: float, tif: TIF = TIF.DAY) -> bool:
        """Place a Stop order (best-effort UI automation)."""
        try:
            if not self.load_symbol(symbol):
                print(f"Aborting stop order: failed to load symbol {symbol}")
                return False

            def _set_input_value(el, value: str) -> None:
                """Set an <input> value robustly across UI variants."""
                # TradeZero quantity inputs have JS formatters that corrupt values when using send_keys.
                # Use JS to set value directly and trigger events.
                try:
                    self.driver.execute_script(
                        "arguments[0].removeAttribute('readonly');"
                        "arguments[0].removeAttribute('disabled');"
                        "arguments[0].value = '';"  # Clear first to avoid concatenation bugs
                        "arguments[0].value = arguments[1];"
                        "arguments[0].dispatchEvent(new Event('input', {bubbles:true}));"
                        "arguments[0].dispatchEvent(new Event('change', {bubbles:true}));"
                        "arguments[0].dispatchEvent(new Event('blur', {bubbles:true}));",
                        el,
                        value,
                    )
                except Exception:
                    # Fallback: try native Selenium (less reliable for formatted inputs)
                    try:
                        el.click()
                    except Exception:
                        pass
                    el.send_keys(Keys.CONTROL, "a")
                    el.send_keys(Keys.BACKSPACE)
                    el.send_keys(value)

            # Select a Stop order type by option text (not by index).
            # Some UI variants change element IDs, so try a small set of candidates.
            order_type_el = self._wait_for_any(
                [
                    (By.ID, "trading-order-select-type"),
                    (By.CSS_SELECTOR, "select#trading-order-select-type"),
                    (By.CSS_SELECTOR, "select[id*='order-select-type']"),
                    (By.CSS_SELECTOR, "select[id*='select-type']"),
                ],
                timeout_s=10,
            )
            sel = Select(order_type_el)
            stop_idx = None
            for i, opt in enumerate(sel.options):
                txt = (opt.text or "").strip().lower()
                if "stop" in txt and "limit" not in txt:
                    stop_idx = i
                    break
            if stop_idx is None:
                # Fallback to any option containing 'stop'
                for i, opt in enumerate(sel.options):
                    txt = (opt.text or "").strip().lower()
                    if "stop" in txt:
                        stop_idx = i
                        break
            if stop_idx is None:
                options = [((o.text or "").strip()) for o in sel.options]
                raise RuntimeError(
                    "Could not find a 'Stop' order type in order-type dropdown. "
                    f"Available options: {options}"
                )
            sel.select_by_index(stop_idx)

            # Allow the UI to swap relevant inputs after changing order type.
            time.sleep(0.25)

            # Select TIF
            Select(self.driver.find_element(By.ID, "trading-order-select-time")).select_by_visible_text(tif.value)

            # Quantity
            qty_input = self.driver.find_element(By.ID, "trading-order-input-quantity")
            _set_input_value(qty_input, str(quantity))

            # Stop price input (try common IDs / then any input with 'stop' in its id/name)
            stop_input = None
            for stop_id in [
                # Matches the DOM you pasted.
                "trading-order-input-sprice",
                "trading-order-input-stop",
                "trading-order-input-stop-price",
                "trading-order-input-stopprice",
                "trading-order-input-trigger",
            ]:
                try:
                    stop_input = self.driver.find_element(By.ID, stop_id)
                    break
                except Exception:
                    continue

            if stop_input is None:
                # Some variants use an input adjacent to a 'Stop Price' label.
                try:
                    stop_input = self.driver.find_element(
                        By.XPATH,
                        "//*[contains(translate(normalize-space(.), 'STOP PRICE', 'stop price'), 'stop price')]/following::input[1]",
                    )
                except Exception:
                    stop_input = None

            if stop_input is None:
                try:
                    stop_input = self.driver.find_element(By.CSS_SELECTOR, "input[id*='stop'], input[name*='stop']")
                except Exception:
                    stop_input = None

            if stop_input is None:
                # Last resort: some UIs reuse the price field for stop orders.
                stop_input = self.driver.find_element(By.ID, "trading-order-input-price")

            # Wait briefly for the stop field to become interactable after UI swaps.
            if stop_input is not None:
                for _ in range(25):
                    try:
                        disabled = stop_input.get_attribute("disabled")
                        readonly = stop_input.get_attribute("readonly")
                        if stop_input.is_displayed() and stop_input.is_enabled() and not disabled and not readonly:
                            break
                    except StaleElementReferenceException:
                        break
                    time.sleep(0.1)

            _set_input_value(stop_input, str(stop_price))

            # Click Button
            btn_id = f"trading-order-button-{direction.value}"
            self._safe_click(By.ID, btn_id, retries=1)

            self._handle_order_confirmation_modal()

            print(f"Placed STOP {direction.value.upper()} {quantity} {symbol} @ stop {stop_price}")
            return True
        except Exception as e:
            print(f"Error placing stop order: {e}")
            self._dump_ui_snapshot(f"stop_order_error_{symbol}")
            return False

    def market_order(self, direction: Order, symbol: str, quantity: int, tif: TIF = TIF.DAY):
        """Place a Market Order."""
        try:
            self.load_symbol(symbol)
            
            # Select Market Order (Index 0)
            Select(self.driver.find_element(By.ID, "trading-order-select-type")).select_by_index(0)
            
            # Select TIF
            Select(self.driver.find_element(By.ID, "trading-order-select-time")).select_by_visible_text(tif.value)
            
            # Quantity
            qty_input = self.driver.find_element(By.ID, "trading-order-input-quantity")
            qty_input.clear()
            qty_input.send_keys(quantity)
            
            # Click Button
            btn_id = f"trading-order-button-{direction.value}"
            self._safe_click(By.ID, btn_id, retries=1)

            self._handle_order_confirmation_modal()
            
            print(f"Placed MARKET {direction.value.upper()} {quantity} {symbol}")
            return True
        except Exception as e:
            print(f"Error placing market order: {e}")
            return False

    def get_portfolio(self):
        """Get current portfolio as DataFrame."""
        try:
            # Ensure Portfolio tab is active
            self._safe_click(By.ID, "portfolio-tab-op-1", retries=1)
            try:
                WebDriverWait(self.driver, 6).until(
                    lambda d: d.find_elements(By.CSS_SELECTOR, "#opTable-1 tbody tr")
                    or d.find_elements(By.XPATH, '//*[@id="opTable-1"]/tbody/tr/td')
                )
            except Exception:
                time.sleep(0.5)
            
            # Check if empty
            try:
                empty_msg = self.driver.find_element(By.XPATH, '//*[@id="opTable-1"]/tbody/tr/td').text
                if "no open positions" in empty_msg.lower():
                    return pd.DataFrame()
            except:
                pass

            table = self.driver.find_element(By.ID, "opTable-1")
            rows = table.find_elements(By.CSS_SELECTOR, "tbody tr")

            out: list[dict] = []
            for r in rows:
                tds = r.find_elements(By.CSS_SELECTOR, "td")
                if not tds:
                    continue

                # Empty-state row is usually a single-cell message.
                if len(tds) == 1 and "no open positions" in (tds[0].text or "").lower():
                    return pd.DataFrame()

                symbol = (tds[0].text or "").strip().upper()
                if not symbol:
                    continue

                qty_txt = ""
                if len(tds) >= 3:
                    qty_txt = tds[2].text or ""
                qty_txt = qty_txt.replace(",", "").strip()
                try:
                    qty = float(qty_txt)
                except Exception:
                    qty = 0.0

                out.append({"symbol": symbol, "qty": qty})

            return pd.DataFrame(out)
        except Exception as e:
            print(f"Error reading portfolio: {e}")
            return None

    def get_active_orders(self):
        """Get active orders as DataFrame."""
        try:
            # Click Active Orders tab
            self._safe_click(By.ID, "portfolio-tab-ao-1", retries=1)
            # Give the table time to populate; headless mode can be slower.
            try:
                WebDriverWait(self.driver, 6).until(
                    lambda d: d.find_elements(By.XPATH, '//*[@id="aoTable-1"]/tbody/tr[@order-id]')
                    or d.find_elements(By.XPATH, '//*[@id="aoTable-1"]/tbody/tr/td')
                )
            except Exception:
                time.sleep(0.5)
            
            # Check if empty
            orders = self.driver.find_elements(By.XPATH, '//*[@id="aoTable-1"]/tbody/tr[@order-id]')
            if not orders:
                return pd.DataFrame()

            table = self.driver.find_element(By.ID, "aoTable-1")

            # Header cells live in the sibling header table within the tab container.
            headers: list[str] = []
            try:
                header_cells = self.driver.find_elements(
                    By.CSS_SELECTOR,
                    "#portfolio-content-tab-ao-1 table.table-1 thead tr th",
                )
                headers = [((h.text or "").strip() or f"col_{i}") for i, h in enumerate(header_cells)]
            except Exception:
                headers = []

            rows = table.find_elements(By.CSS_SELECTOR, "tbody tr")

            out: list[dict] = []
            for r in rows:
                order_id = (r.get_attribute("order-id") or "").strip()
                tds = r.find_elements(By.CSS_SELECTOR, "td")
                if not tds:
                    continue

                # Empty-state row (single message cell)
                if len(tds) == 1:
                    continue

                cell_texts = [((td.text or "").strip()) for td in tds]

                # Map all cells to headers if possible (trim/pad as needed).
                row_dict: dict[str, str] = {}
                if headers and len(headers) == len(cell_texts):
                    row_dict = {headers[i]: cell_texts[i] for i in range(len(headers))}
                elif headers and len(headers) < len(cell_texts):
                    row_dict = {headers[i]: cell_texts[i] for i in range(len(headers))}
                    for j in range(len(headers), len(cell_texts)):
                        row_dict[f"col_{j}"] = cell_texts[j]
                else:
                    row_dict = {f"col_{i}": cell_texts[i] for i in range(len(cell_texts))}

                # Heuristic mapping: the first cell is usually cancel button.
                # We primarily need a stable ref number for cancel_order().
                symbol = ""
                if len(tds) >= 3:
                    symbol = (tds[2].text or "").strip().upper()

                qty_txt = ""
                if len(tds) >= 5:
                    qty_txt = tds[4].text or ""
                qty_txt = qty_txt.replace(",", "").strip()
                try:
                    qty = float(qty_txt)
                except Exception:
                    qty = 0.0

                # Always include stable fields.
                row_dict.update({"ref_number": order_id, "symbol": symbol, "qty": qty})
                out.append(row_dict)

            return pd.DataFrame(out)
        except Exception as e:
            print(f"Error reading active orders: {e}")
            return None

    def get_inactive_orders(self):
        """Get inactive orders (filled/cancelled/rejected) as DataFrame."""
        try:
            self._safe_click(By.ID, "portfolio-tab-io-1", retries=1)
            try:
                WebDriverWait(self.driver, 6).until(
                    lambda d: d.find_elements(By.XPATH, '//*[@id="ioTable-1"]/tbody/tr')
                    or d.find_elements(By.XPATH, '//*[@id="ioTable-1"]/tbody/tr/td')
                )
            except Exception:
                time.sleep(0.5)

            rows_any = self.driver.find_elements(By.XPATH, '//*[@id="ioTable-1"]/tbody/tr')
            if not rows_any:
                return pd.DataFrame()

            table = self.driver.find_element(By.ID, "ioTable-1")

            headers: list[str] = []
            try:
                header_cells = self.driver.find_elements(
                    By.CSS_SELECTOR,
                    "#portfolio-content-tab-io-1 table.table-1 thead tr th",
                )
                headers = [((h.text or "").strip() or f"col_{i}") for i, h in enumerate(header_cells)]
            except Exception:
                headers = []

            rows = table.find_elements(By.CSS_SELECTOR, "tbody tr")

            out: list[dict] = []
            for r in rows:
                order_id = (r.get_attribute("order-id") or "").strip()
                tds = r.find_elements(By.CSS_SELECTOR, "td")
                if not tds:
                    continue

                # Empty-state row (single message cell)
                if len(tds) == 1:
                    msg = (tds[0].text or "").strip().lower()
                    if msg:
                        # Most likely an empty-state message.
                        return pd.DataFrame()
                    continue

                cell_texts = [((td.text or "").strip()) for td in tds]

                row_dict: dict[str, str] = {}
                if headers and len(headers) == len(cell_texts):
                    row_dict = {headers[i]: cell_texts[i] for i in range(len(headers))}
                elif headers and len(headers) < len(cell_texts):
                    row_dict = {headers[i]: cell_texts[i] for i in range(len(headers))}
                    for j in range(len(headers), len(cell_texts)):
                        row_dict[f"col_{j}"] = cell_texts[j]
                else:
                    row_dict = {f"col_{i}": cell_texts[i] for i in range(len(cell_texts))}

                symbol = ""
                if len(tds) >= 3:
                    symbol = (tds[2].text or "").strip().upper()

                qty_txt = ""
                if len(tds) >= 5:
                    qty_txt = tds[4].text or ""
                qty_txt = qty_txt.replace(",", "").strip()
                try:
                    qty = float(qty_txt)
                except Exception:
                    qty = 0.0

                row_dict.update({"ref_number": order_id, "symbol": symbol, "qty": qty})
                out.append(row_dict)

            return pd.DataFrame(out)
        except Exception as e:
            print(f"Error reading inactive orders: {e}")
            return None

    def get_notifications(self, max_items: int = 50):
        """Get the most recent notifications as a DataFrame.

        TradeZero often reports rejects/locate issues in the Notifications panel rather
        than in the orders tables.
        """
        try:
            # Notifications are usually always visible in the left column.
            items = self.driver.find_elements(By.CSS_SELECTOR, "#notifications-list-1 li")
            out: list[dict] = []
            for el in items[-max_items:]:
                # Try structured parsing first (date/title/message spans)
                try:
                    date_el = el.find_element(By.CSS_SELECTOR, "span.date")
                    title_el = el.find_element(By.CSS_SELECTOR, "span.title")
                    message_el = el.find_element(By.CSS_SELECTOR, "span.message")
                    
                    date = (date_el.text or "").strip()
                    title = (title_el.text or "").strip()
                    message = (message_el.text or "").strip()
                    
                    if message:
                        out.append({"date": date, "title": title, "message": message})
                except Exception:
                    # Fallback to full text if structured parsing fails
                    txt = (el.text or "").strip()
                    if txt:
                        out.append({"date": "", "title": "", "message": txt})
            return pd.DataFrame(out)
        except Exception as e:
            print(f"Error reading notifications: {e}")
            return None

    def cancel_order(self, order_id: str):
        """Cancel an order by Reference Number."""
        try:
            self._safe_click(By.ID, "portfolio-tab-ao-1", retries=1)
            time.sleep(0.5)
            
            # Find the row with this order ID
            # Note: TradeZero might prefix with 'S.' or similar in the table, but the attribute might be clean
            # The shner-elmo code suggests the attribute is 'order-id'
            
            # We need to find the cancel button for this order
            # XPath: //tr[@order-id='{order_id}']/td[@class='red'] (Cancel button usually red X)
            
            # Try exact match first
            try:
                btn = self.driver.find_element(By.XPATH, f"//tr[@order-id='{order_id}']//td[contains(@class, 'red')]")
                btn.click()
                print(f"Cancelled order {order_id}")
                return True
            except:
                # Try with S. prefix if user didn't provide it
                try:
                    btn = self.driver.find_element(By.XPATH, f"//tr[@order-id='S.{order_id}']//td[contains(@class, 'red')]")
                    btn.click()
                    print(f"Cancelled order S.{order_id}")
                    return True
                except:
                    print(f"Could not find order {order_id} to cancel")
                    return False
        except Exception as e:
            print(f"Error cancelling order: {e}")
            return False

    def get_equity(self):
        """Get Account Equity from 'Account Value' or 'Total Account Value'."""
        try:
            # Retry loop for values that might load asynchronously
            for _ in range(5):
                # 1. Try Specific ID found in Dashboard (h-equity-value)
                try:
                    el = self.driver.find_element(By.ID, "h-equity-value")
                    text = el.text.replace("$", "").replace(",", "").strip()
                    if text and text != "0.00":
                        return float(text)
                except: pass
                
                # 2. Try generic text search for "Account Value"
                targets = ["Account Value", "Equity", "Total Account Value"]
                for t in targets:
                    try:
                        labels = self.driver.find_elements(By.XPATH, f"//*[contains(text(), '{t}')]")
                        for l in labels:
                            try:
                                sib = l.find_element(By.XPATH, "following-sibling::*")
                                val = sib.text.replace("$", "").replace(",", "").strip()
                                if val and val[0].isdigit() and val != "0.00":
                                    return float(val)
                            except: pass
                    except: continue
                
                time.sleep(1.0) # Wait 1s and retry
            
        except Exception as e:
            print(f"Error scraping equity: {e}")
        return 0.0
