import sys
import os

# Add job_extraction to Python path for driver_utils
script_dir = os.path.dirname(os.path.abspath(__file__))
jobxplore_root = os.path.normpath(os.path.join(script_dir, '..', '..', '..'))
driver_utils_path = os.path.join(jobxplore_root, 'src', 'job_extraction')
if driver_utils_path not in sys.path:
    sys.path.insert(0, driver_utils_path)

from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import NoSuchElementException, TimeoutException, ElementClickInterceptedException, WebDriverException
from selenium.common.exceptions import StaleElementReferenceException
from selenium.webdriver import ActionChains
from pyvirtualdisplay import Display
import time
import csv
import random
import logging
from datetime import datetime
import json
try:
    from driver_utils import create_driver, cleanup_driver
except ImportError as e:
    raise ImportError(f"Could not import driver_utils. Path {driver_utils_path} may be incorrect. Error: {e}")

import re
import math
import uuid

# Configure logging (LOG_FILE env can override when imported from list runner)
def configure_logging():
    log_file = os.getenv("LOG_FILE", "apollo_recruiters.log")
    root_logger = logging.getLogger()
    if root_logger.handlers:
        return
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(levelname)s - %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S',
        handlers=[
            logging.StreamHandler(sys.stdout),
            logging.FileHandler(os.path.join(script_dir, log_file)),
        ],
    )

configure_logging()

DEFAULT_TIMEOUT = 20
SCROLL_PAUSE_TIME = 2
PAGE_LOAD_WAIT = 5
CLICK_WAIT = 0.5
APOLLO_OUTPUT_DIR = os.path.join(script_dir, 'apollo_html')
os.makedirs(APOLLO_OUTPUT_DIR, exist_ok=True)


class AuditRecorder:
    """Optional per-run audit trail (JSONL events + row artifacts). Enable with AUDIT=1."""

    def __init__(self):
        self.enabled = os.getenv("AUDIT", "").lower() in ("1", "true", "yes")
        self.run_id = datetime.now().strftime("%Y%m%d_%H%M%S")
        self.dir = os.path.join(APOLLO_OUTPUT_DIR, "audit", self.run_id) if self.enabled else None
        self.jsonl_path = os.path.join(self.dir, "events.jsonl") if self.dir else None
        if self.enabled:
            os.makedirs(self.dir, exist_ok=True)
            logging.info(f"Audit mode enabled: {self.dir}")

    def event(self, event_name, **fields):
        if not self.enabled:
            return
        payload = {
            "ts": datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f"),
            "event": event_name,
            **fields,
        }
        with open(self.jsonl_path, "a", encoding="utf-8") as handle:
            handle.write(json.dumps(payload, ensure_ascii=False) + "\n")

    def save_row_html(self, record, page, row_index, label):
        if not self.enabled:
            return
        try:
            path = os.path.join(self.dir, f"p{page}_r{row_index}_{label}.html")
            with open(path, "w", encoding="utf-8") as handle:
                handle.write(record.get_attribute("outerHTML"))
            self.event("row_html_saved", page=page, row=row_index, label=label, path=path)
        except Exception as e:
            self.event("row_html_error", page=page, row=row_index, label=label, error=str(e))

    def save_row_screenshot(self, driver, page, row_index, label):
        if not self.enabled:
            return
        try:
            path = os.path.join(self.dir, f"p{page}_r{row_index}_{label}.png")
            driver.save_screenshot(path)
            self.event("row_screenshot_saved", page=page, row=row_index, label=label, path=path)
        except Exception as e:
            self.event("row_screenshot_error", page=page, row=row_index, label=label, error=str(e))


_audit = AuditRecorder()
DEFAULT_PEOPLE_URL_TEMPLATE = (
    "https://app.apollo.io/#/people?"
    "organizationNumEmployeesRanges[]=101%2C200&organizationNumEmployeesRanges[]=201%2C500&"
    "organizationNumEmployeesRanges[]=10001&organizationNumEmployeesRanges[]=5001%2C10000&"
    "organizationNumEmployeesRanges[]=2001%2C5000&organizationNumEmployeesRanges[]=501%2C1000&"
    "organizationNumEmployeesRanges[]=1001%2C2000&organizationNumEmployeesRanges[]=51%2C100&"
    "organizationLocations[]=United%20States&organizationTradingStatus[]=public&"
    "prospectedByCurrentTeam[]=no&personTitles[]=technical%20recruiter&"
    "sortAscending=false&sortByField=sanitized_organization_name_unanalyzed"
)

def get_next_run_output_file(output_dir, stem):
    """Return the next numbered output path, e.g. apollo_recruiter_records_3.csv."""
    pattern = re.compile(re.escape(stem) + r"_(\d+)\.csv$")
    max_run = 0
    if os.path.isdir(output_dir):
        for filename in os.listdir(output_dir):
            match = pattern.match(filename)
            if match:
                max_run = max(max_run, int(match.group(1)))
    next_run = max_run + 1
    return os.path.join(output_dir, f"{stem}_{next_run}.csv")

def setup_virtual_display():
    """Set up virtual display for headless environment."""
    try:
        display = Display(visible=0, size=(1920, 1080))
        display.start()
        logging.info("Virtual display started")
        return display
    except Exception as e:
        logging.error(f"Error setting up virtual display: {e}")
        raise

def save_page_html(driver, page_number, base_folder=None):
    """Save the current page HTML to a file."""
    try:
        base_folder = base_folder or APOLLO_OUTPUT_DIR
        os.makedirs(base_folder, exist_ok=True)
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        html_prefix = os.getenv("HTML_PREFIX", "apollo_recruiters_page_")
        filename = os.path.join(base_folder, f"{html_prefix}{page_number}_{timestamp}.html")
        with open(filename, 'w', encoding='utf-8') as f:
            f.write(driver.page_source)
        logging.info(f"Saved HTML for page {page_number} to {filename}")
    except Exception as e:
        logging.error(f"Error saving page HTML: {e}")

def save_page_screenshot(driver, page_number, base_folder=None):
    """Save a screenshot of the current page."""
    try:
        base_folder = base_folder or APOLLO_OUTPUT_DIR
        os.makedirs(base_folder, exist_ok=True)
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        html_prefix = os.getenv("HTML_PREFIX", "apollo_recruiters_page_")
        filename = os.path.join(base_folder, f"{html_prefix}{page_number}_{timestamp}.png")
        driver.save_screenshot(filename)
        logging.info(f"Saved screenshot for page {page_number} to {filename}")
    except Exception as e:
        logging.error(f"Error saving screenshot: {e}")

def load_cookie_data(cookie_file=None):
    """Load cookie data from external file."""
    if cookie_file is None:
        cookie_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'apollo_cookies.txt')
    try:
        with open(cookie_file, 'r') as file:
            content = file.read().strip()
            logging.info("Cookie file read successfully")
            cookie_json = content.replace('\n', '').replace('    ', '')
            cookies = json.loads(cookie_json)
            logging.info(f"Successfully parsed {len(cookies)} cookies")
            return cookies
    except Exception as e:
        logging.error(f"Error loading cookies: {e}")
        raise

def apply_cookies(driver, cookies):
    """Apply cookies to the browser session."""
    try:
        for cookie in cookies:
            try:
                if 'sameSite' in cookie:
                    del cookie['sameSite']
                if 'storeId' in cookie:
                    del cookie['storeId']
                if 'expirationDate' in cookie:
                    cookie['expiry'] = int(cookie['expirationDate'])
                    del cookie['expirationDate']
                if 'domain' not in cookie:
                    cookie['domain'] = '.apollo.io'
                
                driver.add_cookie(cookie)
            except Exception as e:
                logging.warning(f"Error adding cookie {cookie.get('name', 'unknown')}: {e}")
                continue
        logging.info("Cookies applied successfully")
    except Exception as e:
        logging.error(f"Error applying cookies: {e}")
        raise

def load_cookies(driver, cookie_file=None):
    """Handle the complete cookie loading process."""
    if cookie_file is None:
        cookie_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'apollo_cookies.txt')
    try:
        cookies = load_cookie_data(cookie_file)
        logging.info(f"Successfully loaded {len(cookies)} cookies")
        
        driver.get("https://app.apollo.io/#/login")
        time.sleep(3)
        
        # Click the Google login button
        selectors = [
            "//button[contains(normalize-space(.), 'Log In with Google')]",
            "//button[.//*[normalize-space(text())='Log In with Google']]",
            "button[data-cta-variant='secondary'][type='button']",
            "button[type='button']",
        ]
        
        google_login_button = None
        for selector in selectors:
            try:
                if '//' in selector:
                    elements = driver.find_elements(By.XPATH, selector)
                else:
                    elements = driver.find_elements(By.CSS_SELECTOR, selector)
                    
                if elements:
                    for element in elements:
                        try:
                            text = element.get_attribute('textContent') or element.text or ''
                            if 'log in with google' in text.strip().lower():
                                google_login_button = element
                                break
                        except:
                            continue
                if google_login_button:
                    break
            except Exception as e:
                continue
        
        if google_login_button:
            try:
                google_login_button.click()
            except:
                try:
                    driver.execute_script("arguments[0].click();", google_login_button)
                except:
                    actions = ActionChains(driver)
                    actions.move_to_element(google_login_button).click().perform()
                    
            time.sleep(5)
            driver.get("https://app.apollo.io/")
            time.sleep(3)
            apply_cookies(driver, cookies)
            driver.refresh()
            time.sleep(5)
            
        else:
            raise Exception("Could not find Google login button")
            
    except Exception as e:
        logging.error(f"Error in cookie loading process: {e}")
        raise

def get_progress_text(driver):
    """Read Apollo's table pagination scope, e.g. '1 - 25 of 9,150'."""
    progress_pattern = re.compile(r"\d+\s*-\s*\d+\s+of\s+[\d,]+")
    selectors = [
        (
            By.XPATH,
            "//*[@data-interaction-boundary='Table Pagination']"
            "//*[contains(normalize-space(.), ' of ')]",
        ),
        (By.XPATH, "//*[contains(normalize-space(.), ' of ')]"),
    ]

    for by, selector in selectors:
        for element in driver.find_elements(by, selector):
            text = element.text or element.get_attribute("textContent") or ""
            match = progress_pattern.search(" ".join(text.split()))
            if match:
                return match.group(0)

    return "Progress counter not found"

def parse_progress_stats(progress_text):
    """Parse progress text like '1 - 25 of 9,150'."""
    match = re.search(r"(\d+)\s*-\s*(\d+)\s+of\s+([\d,]+)", progress_text or "")
    if not match:
        return None

    start_row = int(match.group(1))
    end_row = int(match.group(2))
    total_rows = int(match.group(3).replace(",", ""))
    page_size = max(1, end_row - start_row + 1)

    return {
        "start_row": start_row,
        "end_row": end_row,
        "total_rows": total_rows,
        "page_size": page_size,
        "total_pages": max(1, math.ceil(total_rows / page_size)),
    }

def get_current_page_number(driver):
    """Read the current page number from Apollo's table pagination controls."""
    selectors = [
        (
            By.XPATH,
            "//*[@data-interaction-boundary='Table Pagination']"
            "//*[@role='combobox' and @aria-label='Current page']",
        ),
        (
            By.XPATH,
            "//*[@data-interaction-boundary='Table Pagination']"
            "//*[@data-name='items' and @aria-label='Current page']",
        ),
    ]

    for by, selector in selectors:
        for element in driver.find_elements(by, selector):
            text = element.text or element.get_attribute("textContent") or ""
            match = re.search(r"\d+", text)
            if match:
                return int(match.group(0))

    return None

def build_people_url(start_page: int) -> str:
    """Build the people URL for list mode or the default recruiter search."""
    list_url = os.getenv("APOLLO_LIST_URL", "").strip()
    if list_url:
        if re.search(r"[?&]page=\d+", list_url):
            url = re.sub(r"page=\d+", f"page={start_page}", list_url)
        elif "?" in list_url:
            url = f"{list_url}&page={start_page}"
        else:
            url = f"{list_url}?page={start_page}"
        logging.info(f"Using saved-list URL mode (page={start_page})")
        return url
    return f"{DEFAULT_PEOPLE_URL_TEMPLATE}&page={start_page}"


def click_net_new_button(driver):
    """Activate the Net New tab/filter (unsaved people rows)."""
    logging.info("Ensuring Net New view is selected...")
    selectors = [
        (By.XPATH, "//div[@role='radiogroup']//label[.//div[normalize-space(text())='Net New']]"),
        (By.XPATH, "//div[@role='tablist']//*[@role='tab' and contains(normalize-space(.), 'Net New')]"),
        (By.XPATH, "//*[@role='tab' and contains(normalize-space(.), 'Net New')]"),
        (By.XPATH, "//label[.//div[normalize-space(text())='Net New']]"),
        (By.XPATH, "//button[contains(normalize-space(.), 'Net New')]"),
        (By.XPATH, "//label[@for='m5sbretq']"),
    ]

    for by, selector in selectors:
        for element in driver.find_elements(by, selector):
            try:
                if not element.is_displayed():
                    continue
                driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", element)
                time.sleep(CLICK_WAIT)
                try:
                    element.click()
                except Exception:
                    driver.execute_script("arguments[0].click();", element)
                time.sleep(PAGE_LOAD_WAIT)
                logging.info("Net New view selected")
                return True
            except Exception:
                continue

    logging.warning("Could not click Net New tab/filter; continuing with current view.")
    return False

def _has_verified_email_cell(record):
    """True when col 4 shows the post-click verified email UI (not the Access email CTA)."""
    verified_selectors = [
        ".//div[@role='gridcell' and @aria-colindex='4']//a[@data-testid='EditableEmailCell__link']",
        ".//div[@role='gridcell' and @aria-colindex='4']//div[@data-tour-id='email-cell-verified']//a[@data-link-variant='default']",
    ]
    for selector in verified_selectors:
        for element in record.find_elements(By.XPATH, selector):
            if not element.is_displayed():
                continue
            text = (element.text or element.get_attribute("textContent") or "").strip()
            if "Access email" in text:
                continue
            if "@" in text or element.get_attribute("data-testid") == "EditableEmailCell__link":
                return True
    return False


def _read_email_from_cell(record):
    """Return an email address from col 4 if Apollo revealed one."""
    try:
        cell = record.find_element(
            By.XPATH, ".//div[@role='gridcell' and @aria-colindex='4']"
        )
    except NoSuchElementException:
        return None, ""

    cell_text = (cell.text or "").strip()

    # Post-click verified state (EditableEmailCell__link + span.zp_CaeaN)
    email_selectors = [
        ".//div[@role='gridcell' and @aria-colindex='4']//a[@data-testid='EditableEmailCell__link']//span[contains(@class, 'zp_CaeaN')]",
        ".//div[@role='gridcell' and @aria-colindex='4']//div[@data-tour-id='email-cell-verified']//a[@data-testid='EditableEmailCell__link']//span[contains(@class, 'zp_CaeaN')]",
        ".//div[@role='gridcell' and @aria-colindex='4']//div[@data-tour-id='email-cell-verified']//span[contains(@class, 'zp_CaeaN')][contains(text(), '@')]",
        ".//div[@role='gridcell' and @aria-colindex='4']//a[contains(@href, 'mailto:')]",
        ".//span[contains(@class, 'zp_hdyyu')]//span",
        ".//a[contains(@href, 'mailto:')]",
        ".//span[contains(@class, 'zp_hdyyu')]",
    ]
    for email_selector in email_selectors:
        for email_element in record.find_elements(By.XPATH, email_selector):
            email = (email_element.text or email_element.get_attribute("href") or "").strip()
            if email.startswith("mailto:"):
                email = email.replace("mailto:", "")
            if email and "@" in email and "Access email" not in email:
                return email, cell_text

    if cell_text and "@" in cell_text and "Access email" not in cell_text:
        match = re.search(r"[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}", cell_text)
        if match:
            return match.group(0), cell_text

    return None, cell_text


def _has_access_email_button(record):
    """True if the Net New Access email CTA is still present on the row."""
    selectors = [
        ".//button[@data-people-tour='home-hub-save-prospect-access-email']",
        ".//button[@data-tour-id='email-cell-verified'][.//span[normalize-space(text())='Access email']]",
        ".//button[.//span[normalize-space(text())='Access email']]",
    ]
    for selector in selectors:
        for button in record.find_elements(By.XPATH, selector):
            if button.is_displayed():
                return True
    return False


def _person_id_from_record(record):
    """Extract Apollo person ID from the name/link cell."""
    for xpath in (
        ".//a[contains(@href, '/people/')]",
        ".//a[contains(@data-to, '/people/')]",
    ):
        for link in record.find_elements(By.XPATH, xpath):
            for attr in ("href", "data-to"):
                value = link.get_attribute(attr) or ""
                match = re.search(r"/people/([a-f0-9]+)", value)
                if match:
                    return match.group(1)
    return None


def _extract_email_from_prospect_response(data):
    """Pull the first verified email from add_to_my_prospects JSON."""
    if not isinstance(data, dict):
        return None
    if data.get("error"):
        return None

    def _from_item(item):
        if not isinstance(item, dict):
            return None
        email = (item.get("email") or "").strip()
        if email and "@" in email:
            return email
        for entry in item.get("contact_emails") or []:
            email = (entry.get("email") or "").strip()
            if email and "@" in email:
                return email
        contact = item.get("contact")
        if isinstance(contact, dict):
            return _from_item(contact)
        return None

    for bucket in ("contacts", "people"):
        for item in data.get(bucket) or []:
            email = _from_item(item)
            if email:
                return email
    return None


def _prospect_via_api(driver, person_id, page=0, row_num=0):
    """Prospect via POST /api/v1/mixed_people/add_to_my_prospects (works from list view)."""
    payload = {
        "entity_ids": [person_id],
        "analytics_context": "Searcher: Individual Add Button",
        "skip_fetching_people": False,
        "cta_name": "Access email",
        "run_contact_emails_waterfall": True,
        "ui_dynamic_field_request_id": str(uuid.uuid4()),
        "cacheKey": int(time.time() * 1000),
    }
    _audit.event("prospect_api_start", page=page, row=row_num, person_id=person_id)

    try:
        response = driver.execute_async_script(
            """
            const payload = arguments[0];
            const done = arguments[arguments.length - 1];
            fetch('/api/v1/mixed_people/add_to_my_prospects', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'Accept': 'application/json',
                },
                body: JSON.stringify(payload),
                credentials: 'include',
            })
                .then(async (resp) => {
                    const text = await resp.text();
                    let data = null;
                    try { data = JSON.parse(text); } catch (e) { data = { raw: text }; }
                    done({ status: resp.status, data });
                })
                .catch((err) => done({ status: 0, error: String(err) }));
            """,
            payload,
        )
    except Exception as exc:
        logging.warning(f"Prospect API call failed for person {person_id}: {exc}")
        _audit.event("prospect_api_error", page=page, row=row_num, error=str(exc))
        return None

    status = (response or {}).get("status")
    data = (response or {}).get("data") or {}
    if (response or {}).get("error"):
        _audit.event("prospect_api_error", page=page, row=row_num, error=response["error"])
        return None

    email = _extract_email_from_prospect_response(data)
    _audit.event(
        "prospect_api_response",
        page=page,
        row=row_num,
        status=status,
        email=email,
        prospected_count=data.get("num_prospected_people_this_billing_cycle"),
    )
    if email:
        logging.info(f"Email via API for row {row_num}: {email}")
        return email

    if status and status >= 400:
        logging.warning(f"Prospect API HTTP {status} for person {person_id}")
    else:
        logging.warning(f"Prospect API returned no email for person {person_id}")
    return None


def _prospect_via_profile(driver, person_id, page=0, row_num=0):
    """Fallback: open profile page and click Access email (slower, but reliable)."""
    list_url = driver.current_url
    profile_url = f"https://app.apollo.io/#/people/{person_id}"
    _audit.event("prospect_profile_nav", page=page, row=row_num, person_id=person_id, url=profile_url)
    driver.get(profile_url)
    time.sleep(random.uniform(4, 6))

    btn_selectors = [
        "//button[@data-people-tour='home-hub-save-prospect-access-email']",
        "//button[.//span[normalize-space(text())='Access email']]",
    ]
    access_button = None
    for selector in btn_selectors:
        for button in driver.find_elements(By.XPATH, selector):
            if button.is_displayed() and button.is_enabled():
                access_button = button
                break
        if access_button:
            break

    if not access_button:
        logging.warning(f"No Access email button on profile for person {person_id}")
        driver.get(list_url)
        time.sleep(random.uniform(3, 5))
        return None

    _click_access_email_button(driver, access_button, access_button)
    email_timeout = int(os.getenv("EMAIL_TIMEOUT", "45"))
    end_time = time.time() + email_timeout
    email = None
    while time.time() < end_time:
        body_text = driver.find_element(By.TAG_NAME, "body").text
        matches = re.findall(r"[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}", body_text)
        matches = [m for m in matches if "apollo.io" not in m.lower()]
        if matches:
            email = matches[0]
            break
        time.sleep(2)

    _audit.event("prospect_profile_result", page=page, row=row_num, email=email)
    driver.get(list_url)
    time.sleep(random.uniform(4, 6))
    click_net_new_button(driver)
    return email


def _click_access_email_button(driver, record, access_button):
    """Click Access email with scroll + fallbacks."""
    driver.execute_script(
        "arguments[0].scrollIntoView({block: 'center', behavior: 'instant'});",
        access_button,
    )
    time.sleep(random.uniform(1.0, 2.0))
    try:
        ActionChains(driver).move_to_element(access_button).pause(0.2).click().perform()
    except Exception:
        try:
            access_button.click()
        except Exception:
            driver.execute_script("arguments[0].click();", access_button)


def _email_cell_state(record):
    """Summarize col 4 for audit logging."""
    email, cell_text = _read_email_from_cell(record)
    return {
        "email": email,
        "cell_text": (cell_text or "")[:200],
        "has_access_button": _has_access_email_button(record),
        "has_verified_cell": _has_verified_email_cell(record),
    }


def _prospect_via_inline_click(driver, record, index, page=0):
    """Legacy inline-table Access email click (often hangs on Trying Apollo...)."""
    row_id = record.get_attribute("id")
    row_num = index + 1
    email_button_selectors = [
        ".//button[@data-people-tour='home-hub-save-prospect-access-email']",
        ".//button[@data-tour-id='email-cell-verified'][.//span[normalize-space(text())='Access email']]",
        ".//div[@role='gridcell' and @aria-colindex='4']//button[@data-cta-variant='secondary'][.//span[normalize-space(text())='Access email']]",
        ".//button[.//span[normalize-space(text())='Access email']]",
    ]

    for selector in email_button_selectors:
        try:
            if row_id:
                record = driver.find_element(By.ID, row_id)
            access_button = record.find_element(By.XPATH, selector)
            if not (access_button.is_displayed() and access_button.is_enabled()):
                continue

            _click_access_email_button(driver, record, access_button)
            logging.info(f"Clicked inline Access email for record {row_num}")
            _audit.event("access_email_clicked", page=page, row=row_num, row_id=row_id, selector=selector)
            _audit.save_row_screenshot(driver, page, row_num, "after_click")
            _audit.save_row_html(record, page, row_num, "after_click")

            email_timeout = int(os.getenv("EMAIL_TIMEOUT", "90"))
            end_time = time.time() + email_timeout
            last_cell_text = ""
            poll_seconds = float(os.getenv("EMAIL_POLL_SECONDS", "2"))

            while time.time() < end_time:
                if row_id:
                    record = driver.find_element(By.ID, row_id)
                email, last_cell_text = _read_email_from_cell(record)
                if email:
                    _audit.event("email_revealed", page=page, row=row_num, email=email, method="inline")
                    return email
                if last_cell_text and "Trying Apollo" not in last_cell_text:
                    if not _has_access_email_button(record):
                        lowered = last_cell_text.lower()
                        if any(token in lowered for token in ("no email", "not available", "unavailable", "no access")):
                            return "N/A"
                time.sleep(poll_seconds)

            _audit.event("email_timeout", page=page, row=row_num, cell_text=last_cell_text[:200], method="inline")
            return "N/A"
        except NoSuchElementException:
            continue
        except Exception as exc:
            _audit.event("access_email_error", page=page, row=row_num, error=str(exc))
            continue
    return "N/A"


def prospect_person(driver, record, index, page=0):
    """Prospect/save a Net New person and return their email."""
    skip_prospect = os.getenv("SKIP_PROSPECT", os.getenv("SKIP_EMAIL", "")).lower() in ("1", "true", "yes")
    if skip_prospect:
        logging.debug(f"Skipping prospect for record {index + 1} (SKIP_PROSPECT/SKIP_EMAIL set)")
        return "N/A"

    row_id = record.get_attribute("id")
    row_num = index + 1
    _audit.save_row_html(record, page, row_num, "before_click")
    _audit.event("prospect_start", page=page, row=row_num, row_id=row_id, state=_email_cell_state(record))

    email, cell_text = _read_email_from_cell(record)
    if email:
        _audit.event("email_already_visible", page=page, row=row_num, email=email)
        return email

    if not _has_access_email_button(record):
        logging.debug(f"No Access email button for record {row_num} (may already be prospected)")
        _audit.event("no_access_email_button", page=page, row=row_num, row_id=row_id)
        return "N/A"

    person_id = _person_id_from_record(record)
    if not person_id:
        logging.warning(f"Could not resolve person ID for record {row_num}")
        _audit.event("person_id_missing", page=page, row=row_num)
        return "N/A"

    mode = os.getenv("PROSPECT_MODE", "api").lower()
    fallback = os.getenv("PROSPECT_FALLBACK", "profile").lower()

    if mode in ("api", "auto"):
        api_email = _prospect_via_api(driver, person_id, page=page, row_num=row_num)
        if api_email:
            return api_email
        if fallback == "profile":
            profile_email = _prospect_via_profile(driver, person_id, page=page, row_num=row_num)
            if profile_email:
                return profile_email
        if fallback == "click":
            return _prospect_via_inline_click(driver, record, index, page=page)

    if mode == "profile":
        profile_email = _prospect_via_profile(driver, person_id, page=page, row_num=row_num)
        if profile_email:
            return profile_email

    if mode == "click":
        return _prospect_via_inline_click(driver, record, index, page=page)

    logging.warning(f"Prospect failed for record {row_num} (person_id={person_id})")
    _audit.event("prospect_failed", page=page, row=row_num, person_id=person_id)
    return "N/A"


def extract_email(driver, record):
    """Reveal and extract email for a people record."""
    return prospect_person(driver, record, -1)

def extract_tag_values(record, driver, colindex=None):
    """Extract tag chips from industry/keywords columns, expanding +N popups when present."""
    visible_tags = []
    try:
        if colindex is not None:
            base_xpath = f".//div[@role='gridcell' and @aria-colindex='{colindex}']"
        else:
            base_xpath = "."

        tag_elements = record.find_elements(
            By.XPATH, f"{base_xpath}//span[contains(@class, 'zp_z4aAi')]"
        )
        for element in tag_elements:
            try:
                tag_text = element.text.strip()
                if tag_text and not tag_text.startswith('+'):
                    visible_tags.append(tag_text)
            except StaleElementReferenceException:
                continue

        more_button = record.find_elements(
            By.XPATH,
            f"{base_xpath}//span[contains(@class, 'zp_z4aAi') and starts-with(text(), '+')]",
        )
        if not visible_tags and more_button:
            try:
                driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", more_button[0])
                time.sleep(CLICK_WAIT)
                driver.execute_script("arguments[0].click();", more_button[0])
                time.sleep(1)
                popup_tags = WebDriverWait(driver, 5).until(
                    EC.presence_of_all_elements_located(
                        (By.XPATH, "//div[contains(@class, 'zp_RF8MX')]//span[contains(@class, 'zp_z4aAi')]")
                    )
                )
                for tag in popup_tags:
                    tag_text = tag.text.strip()
                    if tag_text and tag_text not in visible_tags and not tag_text.startswith('+'):
                        visible_tags.append(tag_text)
                driver.execute_script("document.elementFromPoint(0, 0).click();")
                time.sleep(CLICK_WAIT)
            except Exception as e:
                logging.debug(f"Could not expand collapsed tag popup: {e}")
        elif more_button and visible_tags:
            try:
                driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", more_button[0])
                time.sleep(CLICK_WAIT)
                driver.execute_script("arguments[0].click();", more_button[0])
                time.sleep(1)
                popup_tags = WebDriverWait(driver, 5).until(
                    EC.presence_of_all_elements_located(
                        (By.XPATH, "//div[contains(@class, 'zp_RF8MX')]//span[contains(@class, 'zp_z4aAi')]")
                    )
                )
                for tag in popup_tags:
                    tag_text = tag.text.strip()
                    if tag_text and tag_text not in visible_tags and not tag_text.startswith('+'):
                        visible_tags.append(tag_text)
                driver.execute_script("document.elementFromPoint(0, 0).click();")
                time.sleep(CLICK_WAIT)
            except Exception as e:
                logging.debug(f"Could not expand tag popup: {e}")
    except Exception as e:
        logging.debug(f"Error extracting tags: {e}")

    return visible_tags

def process_record(driver, record, index, output_file, missing_counts=None, current_page=0):
    """Process a single recruiter record."""
    def mark_missing(field_name):
        if missing_counts is not None:
            missing_counts[field_name] = missing_counts.get(field_name, 0) + 1

    data = {
        "Name": "N/A",
        "Title": "N/A",
        "Company": "N/A",
        "Email": "N/A",
        "Links": "N/A",
        "Location": "N/A",
        "# Employees": "N/A",
        "Industry": "N/A",
        "Keywords": "N/A",
    }

    # Net New people are prospected via Access email (not Save).
    data["Email"] = prospect_person(driver, record, index, page=current_page)
    if data["Email"] == "N/A":
        mark_missing("Email")

    try:
        name_element = record.find_element(
            By.XPATH, ".//a[@data-link-variant='default'][contains(@href, '/people/')]"
        )
        data["Name"] = (name_element.get_attribute("textContent") or name_element.text or "").strip()
    except NoSuchElementException:
        mark_missing("Name")

    try:
        title_element = record.find_element(
            By.XPATH, ".//div[@role='gridcell' and @aria-colindex='2']//span[contains(@class, 'zp_FEm_X')]"
        )
        data["Title"] = title_element.text.strip()
    except NoSuchElementException:
        mark_missing("Title")

    try:
        data["Company"] = record.find_element(
            By.XPATH,
            ".//div[@role='gridcell' and @aria-colindex='3']//span[contains(@class, 'zp_CaeaN')]",
        ).text.strip()
    except NoSuchElementException:
        try:
            data["Company"] = record.find_element(
                By.XPATH, ".//a[contains(@href, '/accounts/')]//span[contains(@class, 'zp_CaeaN')]"
            ).text.strip()
        except NoSuchElementException:
            mark_missing("Company")

    try:
        data["Links"] = record.find_element(
            By.XPATH, ".//div[@role='gridcell' and @aria-colindex='7']//a[contains(@href, 'linkedin')]"
        ).get_attribute("href")
    except NoSuchElementException:
        try:
            data["Links"] = record.find_element(
                By.XPATH, ".//a[contains(@href, 'linkedin')]"
            ).get_attribute("href")
        except NoSuchElementException:
            mark_missing("Links")

    try:
        data["Location"] = record.find_element(
            By.XPATH, ".//div[@role='gridcell' and @aria-colindex='8']//span[contains(@class, 'zp_FEm_X')]"
        ).text.strip()
    except NoSuchElementException:
        mark_missing("Location")

    try:
        data["# Employees"] = record.find_element(
            By.XPATH, ".//div[@role='gridcell' and @aria-colindex='9']//span[@data-count-size]"
        ).text.strip()
    except NoSuchElementException:
        try:
            data["# Employees"] = record.find_element(
                By.XPATH, ".//span[@data-count-size]"
            ).text.strip()
        except NoSuchElementException:
            mark_missing("# Employees")

    industry_tags = extract_tag_values(record, driver, colindex="10")
    if industry_tags:
        data["Industry"] = "; ".join(industry_tags)
    else:
        mark_missing("Industry")

    keyword_tags = extract_tag_values(record, driver, colindex="11")
    if keyword_tags:
        data["Keywords"] = "; ".join(keyword_tags)
    else:
        mark_missing("Keywords")

    with open(output_file, mode='a', newline='', encoding='utf-8') as file:
        writer = csv.writer(file)
        writer.writerow([
            data["Name"], data["Title"], data["Company"], data["Email"], data["Links"],
            data["Location"], data["# Employees"], data["Industry"], data["Keywords"],
        ])

    logging.info(
        f"Collected record {index + 1}: {data['Name']} | {data['Title']} | {data['Company']} | {data['Email']}"
    )
    return True

def navigate_to_next_page(driver, current_page):
    """Navigate to the next page with verification."""
    try:
        wait = WebDriverWait(driver, DEFAULT_TIMEOUT)
        old_progress = get_progress_text(driver)
        next_button = wait.until(
            EC.element_to_be_clickable(
                (
                    By.XPATH,
                    "//*[@data-interaction-boundary='Table Pagination']"
                    "//button[@aria-label='Next' and not(@disabled) and not(@aria-disabled='true')]",
                )
            )
        )
        driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", next_button)
        time.sleep(SCROLL_PAUSE_TIME)
        try:
            next_button.click()
        except Exception:
            driver.execute_script("arguments[0].click();", next_button)

        expected_page = current_page + 1
        wait.until(
            lambda d: (
                get_current_page_number(d) == expected_page
                or get_progress_text(d) != old_progress
            )
        )
        time.sleep(random.uniform(2, 4))
        new_page = get_current_page_number(driver)
        if new_page == expected_page:
            logging.info(f"Successfully navigated to page {new_page}")
            return True, new_page
        logging.error(f"Navigation failed - expected page {expected_page}, found {new_page}")
        return False, current_page
    except Exception as e:
        logging.error(f"Failed to navigate to next page: {e}")
        return False, current_page

def main():
    driver = None
    display = None
    try:
        try:
            start_page = int(os.getenv('START_PAGE', '1'))
            if start_page < 1:
                raise ValueError("START_PAGE must be >= 1")
        except ValueError as e:
            logging.error(f"Invalid page numbers: {e}")
            return

        # Optional explicit end page (if omitted, script auto-detects last page).
        end_page_env = os.getenv('END_PAGE')
        explicit_end_page = None
        if end_page_env:
            try:
                explicit_end_page = int(end_page_env)
                if explicit_end_page < start_page:
                    raise ValueError("END_PAGE must be >= START_PAGE")
            except ValueError as e:
                logging.error(f"Invalid END_PAGE: {e}")
                return

        # Randomized anti-rate-limit break controls.
        try:
            break_every_min_pages = int(os.getenv("BREAK_EVERY_MIN_PAGES", "3"))
            break_every_max_pages = int(os.getenv("BREAK_EVERY_MAX_PAGES", "8"))
            break_min_seconds = int(os.getenv("BREAK_MIN_SECONDS", "20"))
            break_max_seconds = int(os.getenv("BREAK_MAX_SECONDS", "60"))
            if break_every_min_pages < 1 or break_every_max_pages < break_every_min_pages:
                raise ValueError("Invalid BREAK_EVERY_* values")
            if break_min_seconds < 1 or break_max_seconds < break_min_seconds:
                raise ValueError("Invalid BREAK_*_SECONDS values")
        except ValueError as e:
            logging.error(f"Invalid break configuration: {e}")
            return

        logging.info(f"Starting recruiter extraction from page {start_page}")
        logging.info("Tip: run 'python3 check_progress.py --pipeline recruiters' to see resume guidance.")

        display = setup_virtual_display()
        headless = os.getenv("HEADLESS", "1").lower() not in ("0", "false", "no")
        user_data_dir = os.getenv("CHROME_USER_DATA_DIR", "").strip() or None
        logging.info(f"Browser headless={headless}")
        driver = create_driver(
            profile_name="apollo_recruiters",
            headless=headless,
            user_data_dir=user_data_dir,
        )
        time.sleep(random.uniform(1, 3))
        load_cookies(driver)

        filtered_url = build_people_url(start_page)
        logging.info("Navigating to filtered People page...")
        driver.get(filtered_url)
        time.sleep(10)
        click_net_new_button(driver)

        # Determine total pages from pagination scope.
        progress_text = get_progress_text(driver)
        progress_stats = parse_progress_stats(progress_text)
        if not progress_stats:
            logging.error(
                f"Could not parse pagination progress text: '{progress_text}'. "
                "Set END_PAGE manually and retry."
            )
            return

        detected_end_page = progress_stats["total_pages"]
        end_page = min(explicit_end_page, detected_end_page) if explicit_end_page else detected_end_page
        if start_page > end_page:
            logging.info(
                f"START_PAGE={start_page} is beyond detected pages ({end_page}); nothing to process."
            )
            return

        logging.info(
            f"Detected total rows: {progress_stats['total_rows']}, page size: {progress_stats['page_size']}, "
            f"total pages: {detected_end_page}. Processing through page {end_page}."
        )

        output_dir = os.getenv("OUTPUT_DIR")
        if output_dir:
            output_dir = output_dir if os.path.isabs(output_dir) else os.path.join(script_dir, output_dir)
        else:
            output_dir = os.path.join(script_dir, 'apollo_recruiters')
        os.makedirs(output_dir, exist_ok=True)
        output_stem = os.getenv("OUTPUT_STEM", "apollo_recruiter_records")
        resume_output = os.getenv("RESUME_OUTPUT_FILE", "").strip()
        if resume_output:
            output_file = resume_output if os.path.isabs(resume_output) else os.path.join(script_dir, resume_output)
        else:
            output_file = get_next_run_output_file(output_dir, output_stem)
        logging.info(f"Output file will be saved to: {output_file}")
        if resume_output and os.path.isfile(output_file):
            logging.info(f"Resuming into existing CSV ({os.path.basename(output_file)})")
        else:
            with open(output_file, mode='w', newline='', encoding='utf-8') as file:
                writer = csv.writer(file)
                writer.writerow([
                    "Name", "Title", "Company", "Email", "Links",
                    "Location", "# Employees", "Industry", "Keywords",
                ])
            logging.info(f"Created new CSV file with headers (run {os.path.basename(output_file)})")

        current_page = start_page
        total_records = 0
        consecutive_errors = 0
        max_consecutive_errors = 3

        max_records = int(os.getenv('MAX_RECORDS', '0')) or None
        stop_extraction = False
        next_break_page = current_page + random.randint(break_every_min_pages, break_every_max_pages)

        while current_page <= end_page and not stop_extraction:
            try:
                try:
                    WebDriverWait(driver, 10).until(
                        EC.presence_of_element_located(
                            (By.CSS_SELECTOR, "[data-interaction-boundary='Table Pagination']")
                        )
                    )
                    progress_text = get_progress_text(driver)
                except Exception:
                    progress_text = "Progress counter not found"

                logging.info(f"Processing page {current_page} of {end_page} ({progress_text})")
                _audit.event("page_start", page=current_page, progress=progress_text)
                print(f"\n{'='*50}\nProcessing page {current_page} of {end_page}\nProgress: {progress_text}\n{'='*50}\n")

                save_page_html(driver, current_page)
                save_page_screenshot(driver, current_page)

                page_records = 0
                missing_counts = {
                    "Name": 0, "Title": 0, "Company": 0, "Email": 0, "Links": 0,
                    "Location": 0, "# Employees": 0, "Industry": 0, "Keywords": 0,
                }

                records = WebDriverWait(driver, DEFAULT_TIMEOUT).until(
                    EC.presence_of_all_elements_located((By.XPATH, "//div[contains(@id, 'table-row-')]"))
                )
                if not records:
                    raise NoSuchElementException("No records found on page")

                logging.info(f"Found {len(records)} records on page {current_page}")

                for index in range(len(records)):
                    if max_records is not None and total_records >= max_records:
                        logging.info(f"Reached MAX_RECORDS limit ({max_records})")
                        stop_extraction = True
                        break

                    record = driver.find_element(By.XPATH, f"//div[@id='table-row-{index}']")
                    try:
                        if process_record(
                            driver, record, index, output_file, missing_counts, current_page=current_page
                        ):
                            total_records += 1
                            page_records += 1
                            consecutive_errors = 0
                        else:
                            consecutive_errors += 1
                    except Exception as e:
                        logging.error(f"Error processing record {index}: {e}")
                        consecutive_errors += 1

                    if consecutive_errors >= max_consecutive_errors:
                        logging.error("Too many consecutive errors. Stopping execution.")
                        return

                    time.sleep(random.uniform(1, 2))

                missing_summary = ", ".join(
                    f"{field}: {count}" for field, count in missing_counts.items() if count
                )
                if missing_summary:
                    logging.info(f"Missing fields on page {current_page}: {missing_summary}")
                    print(f"Missing fields on page {current_page}: {missing_summary}")

                logging.info(
                    f"Page {current_page} complete - collected {page_records} recruiters (total: {total_records})"
                )
                print(
                    f"Page {current_page} complete - collected {page_records} recruiters (total: {total_records})"
                )
                _audit.event(
                    "page_complete",
                    page=current_page,
                    page_records=page_records,
                    total_records=total_records,
                    progress=get_progress_text(driver),
                )

                if current_page >= next_break_page and current_page < end_page and not stop_extraction:
                    break_seconds = random.randint(break_min_seconds, break_max_seconds)
                    logging.info(
                        f"Taking random cooldown break for {break_seconds}s "
                        f"after page {current_page}."
                    )
                    time.sleep(break_seconds)
                    next_break_page = current_page + random.randint(
                        break_every_min_pages, break_every_max_pages
                    )

                if current_page < end_page and not stop_extraction:
                    success, new_page = navigate_to_next_page(driver, current_page)
                    if success:
                        current_page = new_page
                        consecutive_errors = 0
                    else:
                        consecutive_errors += 1
                        if consecutive_errors >= max_consecutive_errors:
                            break
                        driver.refresh()
                        time.sleep(PAGE_LOAD_WAIT)
                else:
                    break

            except TimeoutException as e:
                logging.error(f"Timeout waiting for records on page {current_page}: {e}")
                consecutive_errors += 1
                if consecutive_errors >= max_consecutive_errors:
                    break
            except Exception as e:
                logging.error(f"Unexpected error on page {current_page}: {e}")
                consecutive_errors += 1
                if consecutive_errors >= max_consecutive_errors:
                    break

        logging.info(f"Total pages processed up to: {current_page}")
        logging.info(f"Total records collected: {total_records}")


    except Exception as e:
        logging.error(f"Script failed: {e}")
        if driver:
            save_page_screenshot(driver, "error")
            save_page_html(driver, "error")
    finally:
        if driver:
            cleanup_driver(driver)
            logging.info("Driver closed")
        if display:
            display.stop()
            logging.info("Virtual display stopped")

if __name__ == "__main__":
    main()
