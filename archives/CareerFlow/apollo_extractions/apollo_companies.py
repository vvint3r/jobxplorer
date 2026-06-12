import sys
import os

# Add job_extraction to Python path for driver_utils
script_dir = os.path.dirname(os.path.abspath(__file__))
jobxplore_root = os.path.normpath(os.path.join(script_dir, '..', '..', '..'))
driver_utils_path = os.path.join(jobxplore_root, 'src', 'job_extraction')
if driver_utils_path not in sys.path:
    sys.path.insert(0, driver_utils_path)

try:
    from driver_utils import create_driver, cleanup_driver
except ImportError as e:
    raise ImportError(f"Could not import driver_utils. Path {driver_utils_path} may be incorrect. Error: {e}")

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
import re
import math

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S',
    handlers=[
        logging.StreamHandler(sys.stdout),  # Add console output
        logging.FileHandler('apollo_companies.log')  # Keep file logging
    ]
)

# Constants
DEFAULT_TIMEOUT = 20
SCROLL_PAUSE_TIME = 2
PAGE_LOAD_WAIT = 5
CLICK_WAIT = 0.5
APOLLO_HTML_DIR = os.path.join(script_dir, 'apollo_html')
DEFAULT_SEARCH_URL_TEMPLATE = (
    "https://app.apollo.io/#/companies?"
    "organizationNumEmployeesRanges[]=101%2C200&organizationNumEmployeesRanges[]=201%2C500&"
    "organizationNumEmployeesRanges[]=10001&organizationNumEmployeesRanges[]=5001%2C10000&"
    "organizationNumEmployeesRanges[]=2001%2C5000&organizationNumEmployeesRanges[]=501%2C1000&"
    "organizationNumEmployeesRanges[]=1001%2C2000&organizationNumEmployeesRanges[]=51%2C100&"
    "organizationLocations[]=United%20States&organizationTradingStatus[]=public&"
    "prospectedByCurrentTeam[]=no&sortAscending=false&sortByField=sanitized_organization_name_unanalyzed"
)

def get_next_run_output_file(output_dir, stem):
    """Return the next numbered output path, e.g. apollo_records_companies_3.csv."""
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

def add_random_delays():
    """Add random delay between actions."""
    time.sleep(random.uniform(2, 5))

def save_page_html(driver, page_number, base_folder=None):
    """Save the current page HTML to a file."""
    try:
        if base_folder is None:
            base_folder = APOLLO_HTML_DIR
        # Create directory if it doesn't exist
        os.makedirs(base_folder, exist_ok=True)
        
        # Generate filename with timestamp
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        html_prefix = os.getenv("HTML_PREFIX", "apollo_companies_page_")
        filename = os.path.join(base_folder, f"{html_prefix}{page_number}_{timestamp}.html")
        
        # Save the page source
        with open(filename, 'w', encoding='utf-8') as f:
            f.write(driver.page_source)
        logging.info(f"Saved HTML for page {page_number} to {filename}")
        
    except Exception as e:
        logging.error(f"Error saving page HTML: {e}")

def load_cookie_data(cookie_file=None):
    """Load cookie data from external file."""
    if cookie_file is None:
        cookie_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'apollo_cookies.txt')
    try:
        with open(cookie_file, 'r') as file:
            content = file.read().strip()
            logging.info("Cookie file read successfully")
            
            # Clean up the content without logging it
            cookie_json = content.replace('\n', '').replace('    ', '')
            
            # Parse the JSON
            cookies = json.loads(cookie_json)
            logging.info(f"Successfully parsed {len(cookies)} cookies")
            return cookies
            
    except FileNotFoundError:
        logging.error(f"Cookie file not found: {cookie_file}")
        raise
    except json.JSONDecodeError as e:
        logging.error(f"Error parsing cookies JSON: {e}")
        raise
    except Exception as e:
        logging.error(f"Unexpected error loading cookies: {e}")
        raise

def apply_cookies(driver, cookies):
    """Apply cookies to the browser session."""
    try:
        for cookie in cookies:
            try:
                # Remove problematic keys
                if 'sameSite' in cookie:
                    del cookie['sameSite']
                if 'storeId' in cookie:
                    del cookie['storeId']
                # Handle expirationDate
                if 'expirationDate' in cookie:
                    cookie['expiry'] = int(cookie['expirationDate'])
                    del cookie['expirationDate']
                # Add domain if missing
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

def save_page_screenshot(driver, page_number, base_folder=None):
    """Save a screenshot of the current page."""
    try:
        if base_folder is None:
            base_folder = APOLLO_HTML_DIR
        # Create directory if it doesn't exist
        os.makedirs(base_folder, exist_ok=True)
        
        # Generate filename with timestamp
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        html_prefix = os.getenv("HTML_PREFIX", "apollo_companies_page_")
        filename = os.path.join(base_folder, f"{html_prefix}{page_number}_{timestamp}.png")
        
        # Save the screenshot
        driver.save_screenshot(filename)
        logging.info(f"Saved screenshot for page {page_number} to {filename}")
        
    except Exception as e:
        logging.error(f"Error saving screenshot: {e}")

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

def navigate_to_page(driver, target_page):
    """Navigate to a specific page using direct URL."""
    try:
        logging.info(f"Attempting to navigate to page {target_page}")
        
        # Use the exact URL format with the target page
        url = f"https://app.apollo.io/#/people?page={target_page}&organizationNumEmployeesRanges[]=101%2C200&organizationNumEmployeesRanges[]=201%2C500&organizationNumEmployeesRanges[]=10001&organizationNumEmployeesRanges[]=5001%2C10000&organizationNumEmployeesRanges[]=2001%2C5000&organizationNumEmployeesRanges[]=501%2C1000&organizationNumEmployeesRanges[]=1001%2C2000&organizationNumEmployeesRanges[]=51%2C100&organizationLocations[]=United%20States&organizationTradingStatus[]=public&sortByField=%5Bnone%5D&sortAscending=false"
        
        logging.info(f"Navigating to URL: {url}")
        driver.get(url)
        time.sleep(5)  # Wait for page load
        
        # Take screenshot after navigation
        save_page_screenshot(driver, f"page_{target_page}")
        save_page_html(driver, f"page_{target_page}")
        
        # Verify navigation by checking the page number
        try:
            # Wait for records to be present
            WebDriverWait(driver, 20).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, "div[role='rowgroup']"))
            )
            
            # Verify we're on the correct page by checking the pagination control.
            WebDriverWait(driver, 10).until(
                EC.presence_of_element_located(
                    (By.CSS_SELECTOR, "[data-interaction-boundary='Table Pagination']")
                )
            )
            actual_page = get_current_page_number(driver)
            logging.info(f"Current page shows: {actual_page}, Target was: {target_page}")
            
            if target_page == actual_page:
                logging.info(f"Successfully navigated to page {target_page}")
                return True
            else:
                logging.error(f"Navigation verification failed - Expected page {target_page}, but found page {actual_page}")
                return False
                
        except TimeoutException:
            logging.error(f"Failed to verify navigation to page {target_page}")
            save_page_screenshot(driver, f"page_{target_page}_verification_failed")
            save_page_html(driver, f"page_{target_page}_verification_failed")
            return False
            
    except Exception as e:
        logging.error(f"Error navigating to page {target_page}: {e}")
        save_page_screenshot(driver, f"page_{target_page}_error")
        save_page_html(driver, f"page_{target_page}_error")
        return False

def build_companies_url(start_page: int) -> str:
    """Build the companies URL for either saved-list mode or default search filters."""
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

    return f"{DEFAULT_SEARCH_URL_TEMPLATE}&page={start_page}"


def click_net_new_button(driver):
    """Activate the Net New tab/filter (unsaved rows in a list or search)."""
    logging.info("Ensuring Net New view is selected...")
    selectors = [
        (By.XPATH, "//div[@role='radiogroup']//label[.//div[normalize-space(text())='Net New']]"),
        (By.XPATH, "//div[@role='tablist']//*[@role='tab' and contains(normalize-space(.), 'Net New')]"),
        (By.XPATH, "//*[@role='tab' and contains(normalize-space(.), 'Net New')]"),
        (By.XPATH, "//label[.//div[normalize-space(text())='Net New']]"),
        (By.XPATH, "//button[contains(normalize-space(.), 'Net New')]"),
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
        if more_button:
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


def process_record(driver, record, index, output_file, current_page, total_records, page_records, missing_counts=None):
    """Process a single record with proper error handling."""
    def mark_missing(field_name):
        if missing_counts is not None:
            missing_counts[field_name] = missing_counts.get(field_name, 0) + 1

    try:
        save_clicked = False
        skip_save = os.getenv("SKIP_SAVE", "").lower() in ("1", "true", "yes")
        save_button_selectors = [] if skip_save else [
            ".//button[.//span[normalize-space(text())='Save']]",
            ".//button[.//span[contains(text(), 'Save')]]",
            ".//button[contains(normalize-space(.), 'Save')]",
        ]
        for selector in save_button_selectors:
            try:
                save_button = record.find_element(By.XPATH, selector)
                driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", save_button)
                time.sleep(CLICK_WAIT)
                try:
                    save_button.click()
                except Exception:
                    driver.execute_script("arguments[0].click();", save_button)
                time.sleep(CLICK_WAIT)
                save_clicked = True
                logging.info(f"Clicked Save for record {index}")
                break
            except NoSuchElementException:
                continue
        if not save_clicked:
            logging.debug(f"No Save button for record {index} (may already be saved)")

        # Extract data with proper error handling
        data = {
            'company': "N/A",
            'links': "N/A",
            'location': "N/A",
            'employees': "N/A",
            'industry': "N/A",
            'keywords': "N/A"
        }

        # Company name (col 1)
        try:
            data['company'] = record.find_element(
                By.XPATH,
                ".//div[@role='gridcell' and @aria-colindex='1']//a[@data-link-variant='default']/span",
            ).text.strip()
        except NoSuchElementException:
            try:
                data['company'] = record.find_element(
                    By.XPATH,
                    ".//div[@role='gridcell' and @aria-colindex='1']//span[contains(@class, 'zp_CaeaN')]",
                ).text.strip()
            except NoSuchElementException:
                mark_missing("Company")
                logging.debug(f"Company name not found for record {index}")

        # LinkedIn URL
        try:
            links_element = record.find_element(By.XPATH, ".//a[contains(@href, 'linkedin.com/company')]")
            data['links'] = links_element.get_attribute("href")
        except NoSuchElementException:
            try:
                links_element = record.find_element(By.XPATH, ".//a[contains(@href, 'linkedin')]")
                data['links'] = links_element.get_attribute("href")
            except NoSuchElementException:
                mark_missing("LinkedIn URL")
                logging.debug(f"LinkedIn URL not found for record {index}")

        # Location (col 7)
        try:
            data['location'] = record.find_element(
                By.XPATH,
                ".//div[@role='gridcell' and @aria-colindex='7']//span[contains(@class, 'zp_FEm_X')]",
            ).text.strip()
        except NoSuchElementException:
            mark_missing("Location")
            logging.debug(f"Location not found for record {index}")

        # Employee count (col 4)
        try:
            data['employees'] = record.find_element(
                By.XPATH,
                ".//div[@role='gridcell' and @aria-colindex='4']//span[@data-count-size]",
            ).text.strip()
        except NoSuchElementException:
            try:
                data['employees'] = record.find_element(
                    By.XPATH, ".//span[@data-count-size]"
                ).text.strip()
            except NoSuchElementException:
                mark_missing("Employee count")
                logging.debug(f"Employee count not found for record {index}")

        # Industry (col 5)
        industry_tags = extract_tag_values(record, driver, colindex="5")
        if industry_tags:
            data['industry'] = '; '.join(industry_tags)
        else:
            mark_missing("Industry")
            logging.debug(f"Industry not found for record {index}")

        # Keywords (col 6)
        keyword_tags = extract_tag_values(record, driver, colindex="6")
        if keyword_tags:
            data['keywords'] = '; '.join(keyword_tags)
        else:
            mark_missing("Keywords")
            logging.debug(f"Keywords not found for record {index}")

        # Write data to CSV file with proper error handling
        try:
            with open(output_file, mode='a', newline='', encoding='utf-8') as file:
                writer = csv.writer(file)
                writer.writerow([
                    data['company'],
                    data['links'],
                    data['location'],
                    data['employees'],
                    data['industry'],
                    data['keywords']
                ])
        except IOError as e:
            logging.error(f"Failed to write record to CSV: {e}")
            raise

        return True

    except Exception as e:
        logging.error(f"Error processing record {index}: {e}")
        return False

def navigate_to_next_page(driver, current_page):
    """Navigate to the next page with proper error handling."""
    try:
        wait = WebDriverWait(driver, DEFAULT_TIMEOUT)
        old_progress = get_progress_text(driver)
        
        # Find and click the Next button
        next_button = wait.until(
            EC.element_to_be_clickable(
                (
                    By.XPATH,
                    "//*[@data-interaction-boundary='Table Pagination']"
                    "//button[@aria-label='Next' and not(@disabled) and not(@aria-disabled='true')]",
                )
            )
        )
        
        # Scroll the button into view
        driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", next_button)
        time.sleep(SCROLL_PAUSE_TIME)
        
        # Click the next button with retry logic
        try:
            next_button.click()
        except Exception:
            driver.execute_script("arguments[0].click();", next_button)
        
        # Wait for Apollo to update the current page or pagination scope.
        expected_page = current_page + 1
        wait.until(
            lambda d: (
                get_current_page_number(d) == expected_page
                or get_progress_text(d) != old_progress
            )
        )
        time.sleep(random.uniform(2, 4))
        
        # Verify page changed
        try:
            new_page = get_current_page_number(driver)
            
            if new_page == expected_page:
                logging.info(f"Successfully navigated to page {new_page}")
                return True, new_page
            else:
                logging.error(f"Navigation failed - Expected page {expected_page}, but found page {new_page}")
                return False, current_page
                
        except TimeoutException:
            logging.error("Could not verify page navigation - timeout waiting for page number")
            return False, current_page
            
    except Exception as e:
        logging.error(f"Failed to navigate to next page: {e}")
        return False, current_page

def main():
    driver = None
    display = None
    temp_dir = None
    try:
        # Get start page from environment variables with validation
        try:
            start_page = int(os.getenv('START_PAGE', '1'))
            if start_page < 1:
                raise ValueError("START_PAGE must be >= 1")
        except ValueError as e:
            logging.error(f"Invalid page numbers: {e}")
            return

        # Optional explicit end page (if omitted, we auto-detect final page)
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

        collect_html_only = os.getenv("COLLECT_HTML_ONLY", "").lower() in ("1", "true", "yes")

        logging.info(f"Starting extraction from page {start_page}")
        if collect_html_only:
            logging.info("COLLECT_HTML_ONLY mode: saving page HTML only (no Save clicks, reparse later).")
        logging.info("Tip: run 'python3 check_progress.py --pipeline companies' to see resume guidance.")
        
        display = setup_virtual_display()
        driver = create_driver(profile_name="apollo_companies")
        
        # Add random delay before starting
        time.sleep(random.uniform(1, 3))
        
        # Load cookies and authenticate
        load_cookies(driver)
        
        # Navigate directly to filtered URL for companies
        filtered_url = build_companies_url(start_page)
        logging.info("Navigating to Companies page...")
        driver.get(filtered_url)
        time.sleep(10)  # Wait for page load
        
        skip_net_new = os.getenv("SKIP_NET_NEW", "").lower() in ("1", "true", "yes")
        if skip_net_new:
            logging.info("SKIP_NET_NEW set: extracting full result set (not just Net New).")
        elif os.getenv("APOLLO_LIST_URL") or os.getenv("FORCE_NET_NEW", "").lower() in ("1", "true", "yes"):
            click_net_new_button(driver)
        else:
            try:
                net_new_button = WebDriverWait(driver, 10).until(
                    EC.presence_of_element_located((By.XPATH, "//label[@for='m5sbretq']"))
                )
                if "zp_Tt1XI" not in (net_new_button.get_attribute("class") or ""):
                    logging.info("Clicking Net New button...")
                    driver.execute_script("arguments[0].click();", net_new_button)
                    time.sleep(5)
            except Exception as e:
                logging.error(f"Error clicking Net New button: {e}")

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

        # Update output file path with error handling
        output_dir = os.getenv("OUTPUT_DIR")
        if output_dir:
            output_dir = output_dir if os.path.isabs(output_dir) else os.path.join(script_dir, output_dir)
        else:
            output_dir = os.path.join(script_dir, "companies")
        try:
            os.makedirs(output_dir, exist_ok=True)
        except OSError as e:
            logging.error(f"Failed to create output directory: {e}")
            raise
            
        output_stem = os.getenv("OUTPUT_STEM", "apollo_records_companies")
        output_file = get_next_run_output_file(output_dir, output_stem)
        logging.info(f"Output file will be saved to: {output_file}")

        try:
            with open(output_file, mode='w', newline='', encoding='utf-8') as file:
                writer = csv.writer(file)
                writer.writerow(["Company", "LinkedIn URL", "Location", "# Employees", "Industry", "Keywords"])
            logging.info(f"Created new CSV file with headers (run {os.path.basename(output_file)})")
        except Exception as e:
            logging.error(f"Failed to access output file: {e}")
            raise

        # Process pages
        current_page = start_page
        total_records = 0
        consecutive_errors = 0
        MAX_CONSECUTIVE_ERRORS = 3
        next_break_page = current_page + random.randint(break_every_min_pages, break_every_max_pages)
        
        while current_page <= end_page:
            try:
                # Get the progress counter text
                try:
                    WebDriverWait(driver, 10).until(
                        EC.presence_of_element_located(
                            (By.CSS_SELECTOR, "[data-interaction-boundary='Table Pagination']")
                        )
                    )
                    progress_text = get_progress_text(driver)
                    logging.info(f"Progress: {progress_text}")
                except Exception as e:
                    progress_text = "Progress counter not found"
                    logging.warning(f"Could not find progress counter: {e}")
                
                logging.info(f"Processing page {current_page} of {end_page}... ({progress_text})")
                print(f"\n{'='*50}")
                print(f"Processing page {current_page} of {end_page}")
                print(f"Progress: {progress_text}")
                print(f"{'='*50}\n")
                
                # Save the HTML for this page
                save_page_html(driver, current_page)

                # Fast path: collect raw HTML only, skip per-record extraction.
                # All visible fields are recoverable later via the reparser.
                if collect_html_only:
                    logging.info(
                        f"COLLECT_HTML_ONLY: saved page {current_page}/{end_page}; advancing."
                    )
                    consecutive_errors = 0
                    if current_page < end_page:
                        time.sleep(random.uniform(1.5, 3.5))
                        success, new_page = navigate_to_next_page(driver, current_page)
                        if success:
                            current_page = new_page
                            continue
                        consecutive_errors += 1
                        if consecutive_errors >= MAX_CONSECUTIVE_ERRORS:
                            logging.error("Too many consecutive errors. Stopping execution.")
                            break
                        driver.refresh()
                        time.sleep(PAGE_LOAD_WAIT)
                        continue
                    else:
                        break

                # Initialize counter for this page
                page_records = 0
                missing_counts = {
                    "Company": 0,
                    "LinkedIn URL": 0,
                    "Location": 0,
                    "Employee count": 0,
                    "Industry": 0,
                    "Keywords": 0,
                }
                
                # Wait until all rows on the page are present
                try:
                    records = WebDriverWait(driver, DEFAULT_TIMEOUT).until(
                        EC.presence_of_all_elements_located((By.XPATH, "//div[contains(@id, 'table-row-')]"))
                    )
                    
                    if not records:
                        raise NoSuchElementException("No records found on page")
                    
                    logging.info(f"Found {len(records)} records on page {current_page}")
                    print(f"\n{'*'*20} STARTING DATA COLLECTION {'*'*20}")
                    print(f"Found {len(records)} records to process on page {current_page}")
                    print(f"{'*'*60}\n")

                    # Process each record
                    for index in range(len(records)):
                        try:
                            record_xpath = f"//div[@id='table-row-{index}']"
                            record = driver.find_element(By.XPATH, record_xpath)
                            
                            # Process the record
                            if process_record(
                                driver,
                                record,
                                index,
                                output_file,
                                current_page,
                                total_records,
                                page_records,
                                missing_counts,
                            ):
                                total_records += 1
                                page_records += 1
                                consecutive_errors = 0  # Reset error counter on success
                            else:
                                consecutive_errors += 1
                                
                            if consecutive_errors >= MAX_CONSECUTIVE_ERRORS:
                                logging.error(f"Too many consecutive errors ({consecutive_errors}). Stopping execution.")
                                return
                            
                        except NoSuchElementException as e:
                            logging.error(f"Error processing record {index}: {e}")
                            consecutive_errors += 1
                            if consecutive_errors >= MAX_CONSECUTIVE_ERRORS:
                                logging.error(f"Too many consecutive errors ({consecutive_errors}). Stopping execution.")
                                return
                            continue

                    # Report progress for this page
                    missing_summary = ", ".join(
                        f"{field}: {count}" for field, count in missing_counts.items() if count
                    )
                    if missing_summary:
                        logging.info(f"Missing fields on page {current_page}: {missing_summary}")
                        print(f"Missing fields on page {current_page}: {missing_summary}")
                    else:
                        logging.info(f"Missing fields on page {current_page}: none")
                        print(f"Missing fields on page {current_page}: none")

                    logging.info(
                        f"Page {current_page} complete - {progress_text} - "
                        f"Collected {page_records} companies (Total: {total_records})"
                    )
                    print(
                        f"Page {current_page} complete - {progress_text} - "
                        f"Collected {page_records} companies (Total: {total_records})"
                    )

                    if current_page >= next_break_page and current_page < end_page:
                        break_seconds = random.randint(break_min_seconds, break_max_seconds)
                        logging.info(
                            f"Taking random cooldown break for {break_seconds}s "
                            f"after page {current_page}."
                        )
                        time.sleep(break_seconds)
                        next_break_page = current_page + random.randint(
                            break_every_min_pages, break_every_max_pages
                        )

                    # Navigate to next page if not on last page
                    if current_page < end_page:
                        success, new_page = navigate_to_next_page(driver, current_page)
                        if success:
                            current_page = new_page
                            consecutive_errors = 0  # Reset error counter on successful navigation
                        else:
                            consecutive_errors += 1
                            if consecutive_errors >= MAX_CONSECUTIVE_ERRORS:
                                logging.error(f"Too many consecutive errors ({consecutive_errors}). Stopping execution.")
                                break
                            # Try to refresh the page and continue
                            driver.refresh()
                            time.sleep(PAGE_LOAD_WAIT)
                    else:
                        break
                        
                except TimeoutException as e:
                    logging.error(f"Timeout waiting for records on page {current_page}: {e}")
                    consecutive_errors += 1
                    if consecutive_errors >= MAX_CONSECUTIVE_ERRORS:
                        logging.error(f"Too many consecutive errors ({consecutive_errors}). Stopping execution.")
                        break
                    continue

            except Exception as e:
                logging.error(f"Unexpected error on page {current_page}: {e}")
                consecutive_errors += 1
                if consecutive_errors >= MAX_CONSECUTIVE_ERRORS:
                    logging.error(f"Too many consecutive errors ({consecutive_errors}). Stopping execution.")
                    break
                continue

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
