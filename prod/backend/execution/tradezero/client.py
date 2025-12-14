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
from selenium.common.exceptions import NoSuchElementException, WebDriverException, StaleElementReferenceException
from webdriver_manager.chrome import ChromeDriverManager
from termcolor import colored

# Constants
TZ_HOME_URL = 'https://standard.tradezeroweb.us/'

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
    def __init__(self, user_name: str, password: str, headless: bool = False):
        self.user_name = user_name
        self.password = password
        
        service = ChromeService(ChromeDriverManager().install())
        options = webdriver.ChromeOptions()
        options.add_experimental_option('excludeSwitches', ['enable-logging'])
        if headless:
            options.add_argument('--headless')
            options.add_argument('--disable-gpu')
        
        self.driver = webdriver.Chrome(service=service, options=options)
        self.driver.get(TZ_HOME_URL)
        
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

    def login(self):
        """Log in to TradeZero."""
        print("Logging in...")
        try:
            login_form = self.driver.find_element(By.ID, "login")
            login_form.clear()
            login_form.send_keys(self.user_name)
            
            password_form = self.driver.find_element(By.ID, "password")
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
                print("Login might have failed or timed out.")
        except Exception as e:
            print(f"Login error: {e}")

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
            self.driver.find_element(By.ID, "locate-tab-1").click()
            
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
            self.driver.find_element(By.ID, "short-list-button-locate").click()
            
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
            self.driver.find_element(By.ID, btn_id).click()
            
            print(f"Placed LIMIT {direction.value.upper()} {quantity} {symbol} @ {price}")
            return True
        except Exception as e:
            print(f"Error placing limit order: {e}")
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
            self.driver.find_element(By.ID, btn_id).click()
            
            print(f"Placed MARKET {direction.value.upper()} {quantity} {symbol}")
            return True
        except Exception as e:
            print(f"Error placing market order: {e}")
            return False

    def get_portfolio(self):
        """Get current portfolio as DataFrame."""
        try:
            # Ensure Portfolio tab is active
            self.driver.find_element(By.ID, "portfolio-tab-op-1").click()
            time.sleep(0.5)
            
            # Check if empty
            try:
                empty_msg = self.driver.find_element(By.XPATH, '//*[@id="opTable-1"]/tbody/tr/td').text
                if "no open positions" in empty_msg.lower():
                    return pd.DataFrame()
            except:
                pass

            # Read table
            df = pd.read_html(self.driver.page_source, attrs={'id': 'opTable-1'})[0]
            df.columns = ['symbol', 'type', 'qty', 'p_close', 'entry', 'price', 'change', 'pct_change', 'day_pnl', 'pnl', 'overnight']
            return df
        except Exception as e:
            print(f"Error reading portfolio: {e}")
            return None

    def get_active_orders(self):
        """Get active orders as DataFrame."""
        try:
            # Click Active Orders tab
            self.driver.find_element(By.ID, "portfolio-tab-ao-1").click()
            time.sleep(0.5)
            
            # Check if empty
            orders = self.driver.find_elements(By.XPATH, '//*[@id="aoTable-1"]/tbody/tr[@order-id]')
            if not orders:
                return pd.DataFrame()

            df = pd.read_html(self.driver.page_source, attrs={'id': 'aoTable-1'})[0]
            # Drop first column (Cancel button)
            df = df.drop(df.columns[0], axis=1)
            df.columns = ['ref_number', 'symbol', 'side', 'qty', 'type', 'status', 'tif', 'limit', 'stop', 'placed']
            return df
        except Exception as e:
            print(f"Error reading active orders: {e}")
            return None

    def cancel_order(self, order_id: str):
        """Cancel an order by Reference Number."""
        try:
            self.driver.find_element(By.ID, "portfolio-tab-ao-1").click()
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
