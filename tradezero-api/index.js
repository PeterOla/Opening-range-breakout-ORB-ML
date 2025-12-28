const { Builder, By, Key, until, Select } = require('selenium-webdriver');
const chrome = require('selenium-webdriver/chrome');

const DEFAULT_TZ_HOME_URL = 'https://standard.tradezeroweb.us/';

const Order = {
    BUY: 'buy',
    SELL: 'sell',
    SHORT: 'short',
    COVER: 'cover'
};

const TIF = {
    DAY: 'DAY',
    GTC: 'GTC',
    GTX: 'GTX'
};

class TradeZero {
    /**
     * @param {string} userName 
     * @param {string} password 
     * @param {boolean} headless 
     * @param {string|null} homeUrl 
     */
    constructor(userName, password, headless = false, homeUrl = null) {
        this.userName = userName;
        this.password = password;
        this.homeUrl = (homeUrl || DEFAULT_TZ_HOME_URL).trim();
        this.headless = headless;
        this.driver = null;
    }

    /**
     * Initialize the driver and log in.
     */
    async init() {
        let options = new chrome.Options();
        options.excludeSwitches('enable-logging');
        if (this.headless) {
            options.addArguments('--headless');
            options.addArguments('--disable-gpu');
        }

        this.driver = await new Builder()
            .forBrowser('chrome')
            .setChromeOptions(options)
            .build();

        await this.driver.get(this.homeUrl);
        await this.login();
    }

    async _safeClick(locator, retries = 1) {
        let lastErr = null;
        for (let i = 0; i <= retries; i++) {
            try {
                await this._dismissModalOverlays();
                const el = await this.driver.findElement(locator);
                await el.click();
                return;
            } catch (e) {
                lastErr = e;
                await this._dismissModalOverlays();
                await this.driver.sleep(250);
                // Try JS click
                try {
                    const el = await this.driver.findElement(locator);
                    await this.driver.executeScript("arguments[0].click();", el);
                    return;
                } catch (ignored) {}
            }
        }
        if (lastErr) throw lastErr;
    }

    async _dismissModalOverlays() {
        try {
            if (await this._handleOrderConfirmationModal()) return;

            // Try clicking overlay
            const overlays = await this.driver.findElements(By.css("div.simplemodal-overlay"));
            if (overlays.length > 0) {
                try { await overlays[0].click(); await this.driver.sleep(200); } catch (e) {}
            }

            // Try close buttons
            const selectors = [
                "a.simplemodal-close", "button.simplemodal-close", ".simplemodal-close", "#simplemodal-container a.close"
            ];
            for (let sel of selectors) {
                try {
                    const btn = await this.driver.findElement(By.css(sel));
                    await btn.click();
                    await this.driver.sleep(200);
                    return;
                } catch (e) {}
            }

            // ESC key
            try {
                await this.driver.findElement(By.tagName("body")).sendKeys(Key.ESCAPE);
                await this.driver.sleep(200);
            } catch (e) {}

        } catch (e) {}
    }

    async _handleOrderConfirmationModal() {
        try {
            const container = await this.driver.findElements(By.css("#simplemodal-container"));
            if (container.length === 0) return false;

            const text = (await container[0].getText()).toLowerCase();
            if (!text.includes("order confirmation")) return false;

            // Confirm button
            const xpaths = [
                "//div[@id='simplemodal-container']//button[normalize-space()='Confirm']",
                "//div[@id='simplemodal-container']//a[normalize-space()='Confirm']"
            ];

            for (let xp of xpaths) {
                try {
                    const el = await this.driver.findElement(By.xpath(xp));
                    await el.click();
                    await this.driver.sleep(300);
                    return true;
                } catch (e) {}
            }
            return false;
        } catch (e) {
            return false;
        }
    }

    async login() {
        console.log("Logging in...");
        try {
            let loginForm = null;
            try { loginForm = await this.driver.findElement(By.id("login")); } catch (e) {}

            if (!loginForm) {
                // Fallbacks
                const selectors = ["input[type='email']", "input[name='email']", "input[name='username']"];
                for (let sel of selectors) {
                    try { loginForm = await this.driver.findElement(By.css(sel)); break; } catch (e) {}
                }
            }

            if (!loginForm) throw new Error("Could not find username input");

            await loginForm.clear();
            await loginForm.sendKeys(this.userName);

            let passForm = null;
            try { passForm = await this.driver.findElement(By.id("password")); } catch (e) {}
            
            if (!passForm) {
                const selectors = ["input[type='password']", "input[name='password']"];
                for (let sel of selectors) {
                    try { passForm = await this.driver.findElement(By.css(sel)); break; } catch (e) {}
                }
            }

            if (!passForm) throw new Error("Could not find password input");

            await passForm.clear();
            await passForm.sendKeys(this.password, Key.RETURN);

            // Wait for portfolio
            try {
                await this.driver.wait(until.elementLocated(By.xpath("//*[contains(@id,'portfolio-container')]")), 60000);
                console.log("Login successful.");
                
                // Set default to Limit
                try {
                    const selectEl = await this.driver.findElement(By.id("trading-order-select-type"));
                    const select = new Select(selectEl);
                    await select.selectByIndex(1);
                } catch (e) {}

            } catch (e) {
                console.log("Login timed out or failed.");
            }

        } catch (e) {
            console.error("Login error:", e);
        }
    }

    async currentSymbol() {
        try {
            const el = await this.driver.findElement(By.id('trading-order-symbol'));
            const text = await el.getText();
            return text.replace('(USD)', '').trim();
        } catch (e) {
            return "";
        }
    }

    async loadSymbol(symbol) {
        symbol = symbol.toUpperCase();
        if (symbol === await this.currentSymbol()) return true;

        try {
            const input = await this.driver.findElement(By.id("trading-order-input-symbol"));
            await input.clear();
            await input.sendKeys(symbol, Key.RETURN);
            await this.driver.sleep(500);

            // Wait for price
            for (let i = 0; i < 50; i++) {
                try {
                    const priceEl = await this.driver.findElement(By.id("trading-order-ask"));
                    const priceTxt = (await priceEl.getText()).replace(',', '');
                    if (priceTxt && !isNaN(parseFloat(priceTxt)) && parseFloat(priceTxt) > 0) {
                        return true;
                    }
                } catch (e) {}
                await this.driver.sleep(100);
            }
            console.warn(`Warning: Could not load symbol ${symbol}`);
            return false;
        } catch (e) {
            console.error(`Error loading symbol ${symbol}:`, e);
            return false;
        }
    }

    async getMarketData(symbol) {
        if (!(await this.loadSymbol(symbol))) return null;

        try {
            const ids = {
                open: 'trading-order-open',
                high: 'trading-order-high',
                low: 'trading-order-low',
                close: 'trading-order-close',
                volume: 'trading-order-vol',
                last: 'trading-order-p',
                ask: 'trading-order-ask',
                bid: 'trading-order-bid'
            };

            const data = {};
            for (const [key, id] of Object.entries(ids)) {
                const el = await this.driver.findElement(By.id(id));
                const txt = (await el.getText()).replace(',', '');
                data[key] = txt ? parseFloat(txt) : 0.0;
            }
            return data;
        } catch (e) {
            console.error(`Error getting data for ${symbol}:`, e);
            return null;
        }
    }

    async limitOrder(direction, symbol, quantity, price, tif = TIF.DAY) {
        try {
            await this.loadSymbol(symbol);

            const typeSel = await this.driver.findElement(By.id("trading-order-select-type"));
            await new Select(typeSel).selectByIndex(1); // Limit

            const tifSel = await this.driver.findElement(By.id("trading-order-select-time"));
            await new Select(tifSel).selectByVisibleText(tif);

            const qtyInput = await this.driver.findElement(By.id("trading-order-input-quantity"));
            await qtyInput.clear();
            await qtyInput.sendKeys(quantity);

            const priceInput = await this.driver.findElement(By.id("trading-order-input-price"));
            await priceInput.clear();
            await priceInput.sendKeys(price);

            const btnId = `trading-order-button-${direction}`;
            await this._safeClick(By.id(btnId));

            await this._handleOrderConfirmationModal();
            console.log(`Placed LIMIT ${direction.toUpperCase()} ${quantity} ${symbol} @ ${price}`);
            return true;
        } catch (e) {
            console.error("Error placing limit order:", e);
            return false;
        }
    }

    async marketOrder(direction, symbol, quantity, tif = TIF.DAY) {
        try {
            await this.loadSymbol(symbol);

            const typeSel = await this.driver.findElement(By.id("trading-order-select-type"));
            await new Select(typeSel).selectByIndex(0); // Market

            const tifSel = await this.driver.findElement(By.id("trading-order-select-time"));
            await new Select(tifSel).selectByVisibleText(tif);

            const qtyInput = await this.driver.findElement(By.id("trading-order-input-quantity"));
            await qtyInput.clear();
            await qtyInput.sendKeys(quantity);

            const btnId = `trading-order-button-${direction}`;
            await this._safeClick(By.id(btnId));

            await this._handleOrderConfirmationModal();
            console.log(`Placed MARKET ${direction.toUpperCase()} ${quantity} ${symbol}`);
            return true;
        } catch (e) {
            console.error("Error placing market order:", e);
            return false;
        }
    }

    async exit() {
        if (this.driver) {
            try { await this.driver.close(); } catch (e) {}
            try { await this.driver.quit(); } catch (e) {}
        }
    }
}

module.exports = { TradeZero, Order, TIF };
