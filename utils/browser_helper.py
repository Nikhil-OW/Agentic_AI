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
            headless=False,  # Enforce visual display (headed browser mode)
            args=[
                "--start-maximized",
                "--no-sandbox",
                "--disable-gpu"
            ]
        )
        self.context = await self.browser.new_context(no_viewport=True)
        self.page = await self.context.new_page()
        await self.page.bring_to_front()  # Force browser window to the front
        # Auto-accept dialogs (such as 'Product added' alerts on demoblaze) to prevent blocking the agent
        self.page.on("dialog", lambda dialog: asyncio.create_task(dialog.accept()))
        return self.page

    async def extract_interactive_elements(self):
        """
        Scrapes the viewport DOM, capturing deep form attributes, accessibility labels,
        and element classification types for highly accurate form-filling capabilities.
        """
        if not self.page:
            return []

        elements = await self.page.evaluate("""() => {
            const isVisible = (el) => {
                if (!el) return false;
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

            // Target all native form fields, selectors, and interactive custom roles
            const targetQuery = 'input, button, select, textarea, a, [role="button"], [role="checkbox"], [role="radio"]';

            return Array.from(document.querySelectorAll(targetQuery)).filter(isVisible).map(el => {
                // Determine accurate unique selector targeting rules
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

                // Extract possible dropdown option structures if the element is a SELECT node
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
                    type: el.type || el.getAttribute('role') || 'text',
                    placeholder: el.placeholder || el.getAttribute('aria-label') || null,
                    text: el.innerText ? el.innerText.trim() : (el.value ? el.value.trim() : null),
                    options: optionsList.length > 0 ? optionsList : null,
                    disabled: el.disabled || false,
                    computed_selector: selector
                };
            }).filter(el => el.id || el.text || el.placeholder || el.name || el.options);
        }""")
        return elements

    async def close_session(self):
        """Cleanly tears down the active automation context to prevent memory leaks."""
        if self.page: await self.page.close()
        if self.context: await self.context.close()
        if self.browser: await self.browser.close()
        if self.playwright: await self.playwright.stop()