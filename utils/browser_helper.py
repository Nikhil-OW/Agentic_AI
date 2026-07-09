import sys
import asyncio
from playwright.async_api import async_playwright


class BrowserHelper:
    """Enterprise wrapper handling maximized browser lifecycle and DOM extraction."""

    def __init__(self):
        self.playwright = None
        self.browser = None
        self.context = None
        self.page = None

    async def initialize_maximized_page(self, headless=False):
        """Launches a fully maximized browser instance across Windows setups."""
        self.playwright = await async_playwright().start()
        self.browser = await self.playwright.chromium.launch(
            headless=False,  # Explicitly overrides any background defaults
            args=[
                "--start-maximized",
                "--no-sandbox",
                "--disable-setuid-sandbox",
                "--disable-dev-shm-usage",
                "--disable-blink-features=AutomationControlled",
                "--disable-features=IsolateOrigins,site-per-process"
            ]
        )
        self.context = await self.browser.new_context(no_viewport=True)  # Allows --start-maximized to work natively
        self.page = await self.context.new_page()
        await self.page.bring_to_front()  # Force the OS window manager to bring the browser to focus
        # Auto-accept dialogs (such as 'Product added' alerts on demoblaze) to prevent blocking the agent
        self.page.on("dialog", lambda dialog: asyncio.create_task(dialog.accept()))
        return self.page

    async def extract_interactive_elements(self):
        """
        Scrapes the viewport DOM, capturing deep form attributes, accessibility labels,
        and element classification types for highly accurate form-filling capabilities.
        Trims non-essential tags (SVG, script, style, meta, iframe) to reduce token weight.
        """
        if not self.page:
            return []

        elements = await self.page.evaluate("""() => {
            const isVisible = (el) => {
                if (!el) return false;
                // Strip out scripts, styles, SVGs, meta, and hidden iframe environments
                if (el.closest('script, style, svg, meta, iframe')) {
                    return false;
                }
                const style = window.getComputedStyle(el);
                if (style.display === 'none' || style.visibility === 'hidden') {
                    return false;
                }
                const isFormTag = el.tagName === 'INPUT' || el.tagName === 'SELECT' || el.tagName === 'TEXTAREA';
                if (parseFloat(style.opacity || '1') === 0 && !isFormTag) {
                    return false;
                }
                const rect = el.getBoundingClientRect();
                if (rect.width === 0 || rect.height === 0) {
                    if (el.tagName !== 'A' || !el.innerText.trim()) {
                        return false;
                    }
                }
                let parent = el.parentElement;
                while (parent) {
                    const parentStyle = window.getComputedStyle(parent);
                    if (parentStyle.display === 'none' || parentStyle.visibility === 'hidden') {
                        return false;
                    }
                    parent = parent.parentElement;
                }
                return true;
            };

            // Scrape form controls, links, headings, alerts and errors
            const targetQuery = 'input, button, select, textarea, a, [role="button"], [role="checkbox"], [role="radio"], h1, h2, h3, .alert, .error';
            const nodes = Array.from(document.querySelectorAll(targetQuery)).filter(isVisible);

            return nodes.map(el => {
                const tag = el.tagName.toLowerCase();
                
                // Classify headings and alert boxes as semantic text markers
                const isHeading = ['h1', 'h2', 'h3'].includes(tag);
                const isAlertOrError = el.classList.contains('alert') || el.classList.contains('error') || 
                                      (window.getComputedStyle(el).color === 'rgb(220, 53, 69)') ||
                                      (el.innerText && (el.innerText.toLowerCase().includes('error') || el.innerText.toLowerCase().includes('invalid') || el.innerText.toLowerCase().includes('unable to')));
                
                if (isHeading || isAlertOrError) {
                    return {
                        tag: el.tagName,
                        type: 'text_marker',
                        text: el.innerText ? el.innerText.trim() : null
                    };
                }

                // Associate labeling texts to standard input elements
                let labelText = '';
                if (el.id) {
                    const lbl = document.querySelector(`label[for="${el.id}"]`);
                    if (lbl) labelText = lbl.innerText.trim();
                }
                if (!labelText && el.parentElement) {
                    let parent = el.parentElement;
                    while (parent && parent.tagName !== 'BODY') {
                        if (parent.tagName === 'LABEL') {
                            labelText = parent.innerText.trim();
                            break;
                        }
                        parent = parent.parentElement;
                    }
                }

                // Determine dynamic selectors
                let selector = el.id ? `#${el.id}` : el.name ? `${el.tagName.toLowerCase()}[name="${el.name}"]` : '';
                if (!selector) {
                    if ((el.tagName === 'A' || el.tagName === 'BUTTON') && el.innerText.trim()) {
                        selector = `text="${el.innerText.trim()}"`;
                    } else if (el.type === 'submit' || el.className) {
                        const classClean = Array.from(el.classList).join('.');
                        selector = classClean ? `${el.tagName.toLowerCase()}.${classClean}` : el.tagName.toLowerCase();
                    } else {
                        selector = el.tagName.toLowerCase();
                    }
                }

                let optionsList = [];
                if (el.tagName === 'SELECT') {
                    optionsList = Array.from(el.options).map(opt => ({
                        text: opt.text.trim(),
                        value: opt.value
                    }));
                }

                return {
                    tag: el.tagName,
                    id: el.id || null,
                    name: el.name || null,
                    label: labelText || null,
                    type: el.type || el.getAttribute('role') || 'text',
                    placeholder: el.placeholder || el.getAttribute('aria-label') || null,
                    text: el.innerText ? el.innerText.trim() : (el.value ? el.value.trim() : null),
                    options: optionsList.length > 0 ? optionsList : null,
                    disabled: el.disabled || false,
                    computed_selector: selector
                };
            }).filter(item => {
                if (item.type === 'text_marker') {
                    return item.text && item.text.length > 0;
                }
                return item.id || item.text || item.placeholder || item.name || item.options || item.label;
            });
        }""")
        return elements

    async def close_session(self):
        """Cleanly tears down the active automation context to prevent memory leaks."""
        if self.page: await self.page.close()
        if self.context: await self.context.close()
        if self.browser: await self.browser.close()
        if self.playwright: await self.playwright.stop()