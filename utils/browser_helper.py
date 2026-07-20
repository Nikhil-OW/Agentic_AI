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
        """Launches a fully maximized or background browser instance dynamically."""
        # For this demo phase, explicitly force headed browser launch visibility
        headless = False
        self.playwright = await async_playwright().start()
        launch_args = [
            "--no-sandbox",
            "--disable-setuid-sandbox",
            "--disable-dev-shm-usage",
            "--disable-blink-features=AutomationControlled",
            "--disable-features=IsolateOrigins,site-per-process"
        ]
        if not headless:
            launch_args.append("--start-maximized")
            
        self.browser = await self.playwright.chromium.launch(
            headless=headless,
            slow_mo=1000,
            args=launch_args
        )
        
        if not headless:
            self.context = await self.browser.new_context(no_viewport=True)  # Allows --start-maximized to work natively
        else:
            self.context = await self.browser.new_context(viewport={"width": 1280, "height": 800})
            
        self.page = await self.context.new_page()
        if not headless:
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

        try:
            elements = await self.page.evaluate(r"""() => {
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

                const cleanText = (txt) => {
                    return txt ? txt.replace(/\s+/g, ' ').trim() : '';
                };

                const getLabel = (el) => {
                    if (el.id) {
                        const label = document.querySelector(`label[for="${el.id}"]`);
                        if (label && label.innerText) return cleanText(label.innerText);
                    }
                    const parentLabel = el.closest('label');
                    if (parentLabel && parentLabel.innerText) return cleanText(parentLabel.innerText);
                    
                    let prev = el.previousElementSibling;
                    while (prev) {
                        if (prev.tagName === 'LABEL' && prev.innerText) return cleanText(prev.innerText);
                        prev = prev.previousElementSibling;
                    }
                    return '';
                };

                const hasVisibleModal = () => {
                    const modal = document.querySelector('.modal-container, .modal, [class*="modal"], [class*="Modal"]');
                    if (modal) {
                        const rect = modal.getBoundingClientRect();
                        return rect.width > 0 && rect.height > 0 && window.getComputedStyle(modal).display !== 'none';
                    }
                    return false;
                };

                const allElements = Array.from(document.querySelectorAll('input, select, textarea, button, a, [role="button"], [role="link"], [role="checkbox"], h1, h2, h3, h4, h5, h6, .alert-danger, .alert-error, .error-message, .error-text, [role="alert"]'));
                
                return allElements.map(el => {
                    if (!isVisible(el)) return null;

                    // Spatial container scoping: If modal is present, only discover elements inside it
                    const hasModal = hasVisibleModal();
                    const modalParent = el.closest('.modal-container, .modal, [class*="modal"], [class*="Modal"]');
                    if (hasModal && !modalParent) {
                        return null; // Discard background element
                    }

                    const isHeader = /^H[1-6]$/.test(el.tagName);
                    const isAlert = el.classList.contains('alert-danger') || el.classList.contains('alert-error') || el.classList.contains('error-message') || el.classList.contains('error-text') || el.getAttribute('role') === 'alert';
                    
                    if (isHeader || isAlert) {
                        return {
                            tag: el.tagName,
                            type: isAlert ? 'alert_message' : 'text_marker',
                            text: cleanText(el.innerText || ''),
                            computed_selector: null
                        };
                    }

                    const labelText = getLabel(el);
                    
                    let selector = null;
                    const tagLower = el.tagName.toLowerCase();
                    const text = cleanText(el.innerText || el.value || '');
                    const navParent = el.closest('a, button, li, [role="menuitem"], [role="link"], .menu-item, .nav-item');

                    if (el.id) {
                        selector = `#${el.id}`;
                    } else if (el.name) {
                        selector = `${tagLower}[name="${el.name}"]`;
                    } else if (tagLower === 'a' && text && text.length < 60 && !text.includes('\n')) {
                        selector = `a:has-text("${text}")`;
                    } else if (tagLower === 'button' && text && text.length < 60 && !text.includes('\n')) {
                        selector = `button:has-text("${text}")`;
                    } else if ((tagLower === 'li' || el.getAttribute('role') === 'menuitem') && text && text.length < 60 && !text.includes('\n')) {
                        selector = `${tagLower}:has-text("${text}")`;
                    } else if (navParent && text && text.length < 60 && !text.includes('\n')) {
                        const parentTag = navParent.tagName.toLowerCase();
                        if (parentTag === 'a') {
                            selector = `a:has-text("${text}")`;
                        } else if (parentTag === 'button') {
                            selector = `button:has-text("${text}")`;
                        } else if (parentTag === 'li') {
                            selector = `li:has-text("${text}")`;
                        } else {
                            selector = `:is(a, button, li, [role="menuitem"]):has-text("${text}")`;
                        }
                    } else if (text && text.length < 50 && !text.includes('\n')) {
                        selector = `text="${text}"`;
                    } else if (el.type === 'submit' || el.className) {
                        const classClean = Array.from(el.classList).join('.');
                        selector = classClean ? `${tagLower}.${classClean}` : tagLower;
                    } else {
                        selector = tagLower;
                    }

                    // Prepend modal container scope if inside a dynamic overlay to prevent pointer interception
                    if (modalParent && selector) {
                        const classList = Array.from(modalParent.classList).filter(c => c && c.trim());
                        const parentClass = classList.length > 0 ? '.' + classList.join('.') : '[class*="modal"]';
                        selector = `${parentClass}:visible >> ${selector} >> visible=true`;
                    } else if (selector) {
                        const hasOverlay = !!document.querySelector('.modal-container, .modal, [class*="modal"], [class*="Modal"]');
                        if (hasOverlay) {
                            selector = `${selector} >> visible=true`;
                        }
                    }

                    let optionsList = [];
                    if (el.tagName === 'SELECT') {
                        optionsList = Array.from(el.options).map(opt => ({
                            text: cleanText(opt.text),
                            value: opt.value
                        }));
                    }

                    const rect = el.getBoundingClientRect();
                    const isElVisible = rect.width > 0 && rect.height > 0 && el.offsetWidth > 0 && el.offsetHeight > 0;
                    const visibilityHighlight = isElVisible ? "strictly_visible_in_active_viewport" : "hidden_or_collapsed";

                    return {
                        tag: el.tagName,
                        id: el.id || null,
                        name: el.name || null,
                        label: labelText || null,
                        type: el.type || el.getAttribute('role') || 'text',
                        placeholder: cleanText(el.placeholder || el.getAttribute('aria-label') || '') || null,
                        text: cleanText(el.innerText || el.value || '') || null,
                        options: optionsList.length > 0 ? optionsList : null,
                        disabled: el.disabled || false,
                        computed_selector: selector,
                        visibility_flag: visibilityHighlight
                    };
                }).filter(item => {
                    if (!item) return false;
                    if (item.type === 'text_marker' || item.type === 'alert_message') {
                        return item.text && item.text.length > 0;
                    }
                    return item.id || item.text || item.placeholder || item.name || item.options || item.label || item.computed_selector;
                });
            }""")

            # Post-process elements to disambiguate duplicate computed selectors with nth= indexes
            selector_counts = {}
            for el in elements:
                sel = el.get("computed_selector")
                if sel and not (el.get("type") in ["text_marker", "alert_message"]):
                    selector_counts[sel] = selector_counts.get(sel, 0) + 1

            selector_indices = {}
            for el in elements:
                sel = el.get("computed_selector")
                if sel and not (el.get("type") in ["text_marker", "alert_message"]):
                    if selector_counts[sel] > 1 and ">> nth=" not in sel:
                        idx = selector_indices.get(sel, 0)
                        el["computed_selector"] = f"{sel} >> nth={idx}"
                        selector_indices[sel] = idx + 1

            return elements
        except Exception as e:
            print(f"⚠️ [DOM SCRAPE BYPASS]: Exception during evaluate: {e}")
            return []

    async def close_session(self):
        """Cleanly tears down the active automation context to prevent memory leaks."""
        try:
            if self.page:
                try:
                    self.page.remove_listener("dialog", lambda dialog: None)
                except Exception:
                    pass
                if not self.page.is_closed():
                    await self.page.close()
        except Exception as e:
            print(f"⚠️ Exception during page cleanup: {e}")

        try:
            if self.context:
                await self.context.close()
        except Exception as e:
            print(f"⚠️ Exception during context cleanup: {e}")

        try:
            if self.browser:
                await self.browser.close()
        except Exception as e:
            print(f"⚠️ Exception during browser cleanup: {e}")

        try:
            if self.playwright:
                await self.playwright.stop()
        except Exception as e:
            print(f"⚠️ Exception during playwright cleanup: {e}")
            
        self.page = None
        self.context = None
        self.browser = None
        self.playwright = None