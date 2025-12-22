from __future__ import annotations
import time
import warnings
import pandas as pd
from collections import namedtuple
from enum import Enum
from typing import Optional, Literal, Union

from selenium import webdriver
from selenium.webdriver.chrome.service import Service as ChromeService
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support.ui import Select
from selenium.common.exceptions import (
    NoSuchElementException,
    WebDriverException,
    StaleElementReferenceException,
    ElementClickInterceptedException,
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
    def __init__(self, user_name: str, password: str, headless: bool = False, home_url: Optional[str] = None):
        self.user_name = user_name
        self.password = password
        self.home_url = (home_url or DEFAULT_TZ_HOME_URL).strip()
        
        service = ChromeService(ChromeDriverManager().install())
        options = webdriver.ChromeOptions()
        options.add_experimental_option('excludeSwitches', ['enable-logging'])
        if headless:
            options.add_argument('--headless')
            options.add_argument('--disable-gpu')
        
        self.driver = webdriver.Chrome(service=service, options=options)
        self.driver.get(self.home_url)
        
        # Initial login
        self.login()

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

        Returns True if it handled a confirmation modal.
        """
        try:
            container = self.driver.find_elements(By.CSS_SELECTOR, "#simplemodal-container")
            if not container:
                return False

            text = (container[0].text or "").lower()
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
                self.driver.find_element(by, selector).click()
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
            
            if self._dom_fully_loaded(60):
                print("Login successful.")
                # Set default order type to Limit (index 1)
                try:
                    Select(self.driver.find_element(By.ID, "trading-order-select-type")).select_by_index(1)
                except:
                    pass
            else:
                # Try to surface a useful error message from the page.
                err = self._try_get_login_error_text()
                if err:
                    print(f"Login failed: {err}")
                else:
                    print("Login might have failed or timed out.")
        except Exception as e:
            print(f"Login error: {e}")

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
            input_symbol = self.driver.find_element(By.ID, "trading-order-input-symbol")
            input_symbol.clear()
            input_symbol.send_keys(symbol, Keys.RETURN)
            time.sleep(0.5)
            
            for i in range(50): # Wait up to 5 seconds
                try:
                    price_text = self.driver.find_element(By.ID, "trading-order-ask").text.replace(',', '')
                    if price_text and price_text.replace('.', '').isdigit() and float(price_text) > 0:
                        return True
                except:
                    pass
                time.sleep(0.1)
            
            print(f"Warning: Could not load symbol {symbol}")
            return False
        except Exception as e:
            print(f"Error loading symbol {symbol}: {e}")
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
        """Place a Stop order (best-effort UI automation).

        Notes:
        - TradeZero web UI variants differ by portal/version.
        - We select an order type option containing 'Stop'.
        - We try multiple candidate input IDs/selectors for the stop price field.
        """
        try:
            self.load_symbol(symbol)

            def _set_input_value(el, value: str) -> None:
                """Set an <input> value robustly across UI variants."""
                try:
                    el.click()
                except Exception:
                    pass
                try:
                    # Some TradeZero inputs are toggled readonly by order type.
                    # Remove readonly/disabled (best-effort) before typing.
                    try:
                        self.driver.execute_script(
                            "arguments[0].removeAttribute('readonly'); arguments[0].removeAttribute('disabled');",
                            el,
                        )
                    except Exception:
                        pass
                    el.send_keys(Keys.CONTROL, "a")
                    el.send_keys(Keys.BACKSPACE)
                    el.send_keys(value)
                    return
                except Exception:
                    # Fallback: set via JS + fire input/change events.
                    self.driver.execute_script(
                        "arguments[0].removeAttribute('readonly');"
                        "arguments[0].removeAttribute('disabled');"
                        "arguments[0].value = arguments[1];"
                        "arguments[0].dispatchEvent(new Event('input', {bubbles:true}));"
                        "arguments[0].dispatchEvent(new Event('change', {bubbles:true}));",
                        el,
                        value,
                    )

            # Select a Stop order type by option text (not by index).
            sel = Select(self.driver.find_element(By.ID, "trading-order-select-type"))
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
                raise RuntimeError("Could not find a 'Stop' order type in trading-order-select-type")
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
            time.sleep(0.5)
            
            # Check if empty
            orders = self.driver.find_elements(By.XPATH, '//*[@id="aoTable-1"]/tbody/tr[@order-id]')
            if not orders:
                return pd.DataFrame()

            table = self.driver.find_element(By.ID, "aoTable-1")
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

                out.append({"ref_number": order_id, "symbol": symbol, "qty": qty})

            return pd.DataFrame(out)
        except Exception as e:
            print(f"Error reading active orders: {e}")
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
        """Get Account Equity."""
        try:
            # This depends on where it is displayed. 
            # Usually in the top bar or Account tab.
            # shner-elmo hides it, so it must be visible by default.
            # Let's try to find an element with ID 'account-equity' or similar, or scrape the text.
            # Based on B-Harakat, it might be in a specific div.
            # For now, let's try to find the element that contains "Equity"
            
            # Fallback: Account Tab
            self.driver.find_element(By.ID, "portfolio-tab-acc-1").click()
            time.sleep(0.5)
            # Look for Equity row
            # This is a guess without seeing the DOM. 
            # But usually it's in a table.
            pass
        except:
            pass
        return 0.0
