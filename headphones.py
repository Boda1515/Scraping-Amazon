import time
import pandas as pd
import numpy as np
from bs4 import BeautifulSoup
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from webdriver_manager.chrome import ChromeDriverManager
from selenium.webdriver.chrome.options import Options
import random
import re
import concurrent.futures

# Set up Selenium WebDriver
chrome_options = Options()
chrome_options.add_argument("--headless")
chrome_options.add_argument("--disable-blink-features=AutomationControlled")
chrome_options.add_argument("--no-sandbox")
chrome_options.add_argument("--disable-dev-shm-usage")


def create_driver():
    return webdriver.Chrome(service=Service(ChromeDriverManager().install()), options=chrome_options)


def random_sleep(min_seconds=1, max_seconds=2):
    time.sleep(random.uniform(min_seconds, max_seconds))


def get_element_text(driver, by, value, default=np.nan):
    try:
        wait = WebDriverWait(driver, 5)
        element = wait.until(EC.presence_of_element_located((by, value)))
        return element.text.strip() if element else default
    except Exception:
        return default


def get_element_attribute(driver, by, value, attribute, default=np.nan):
    try:
        wait = WebDriverWait(driver, 5)
        element = wait.until(EC.presence_of_element_located((by, value)))
        return element.get_attribute(attribute).strip() if element else default
    except Exception:
        return default


def clean_text(text):
    text = re.sub(r'[\u200f\u200e]', '', text)
    text = re.sub(r'\s+', ' ', text)
    return text.strip()


def remove_key_from_value(key, value):
    key_cleaned = clean_text(key)
    value_cleaned = clean_text(value)
    if value_cleaned.startswith(key_cleaned):
        return value_cleaned[len(key_cleaned):].strip(" :")
    return value_cleaned


def scrape_product_data(product_url):
    driver = create_driver()
    try:
        driver.get(product_url)
        random_sleep(1, 2)
        soup = BeautifulSoup(driver.page_source, 'html.parser')
        # Handling the price before
        Price_before_discount = soup.find(
            'span', class_="a-size-small aok-offscreen")
        row_price = Price_before_discount.get_text() if Price_before_discount else np.nan

        product_data = {
            "Title": get_element_text(driver, By.ID, "productTitle"),
            "Rate": get_element_attribute(driver, By.CSS_SELECTOR, "span.a-icon-alt", "textContent").strip(),
            "Price": get_element_text(driver, By.CSS_SELECTOR, "#corePriceDisplay_desktop_feature_div .a-price-whole", np.nan),
            "Price Before Discount": row_price,
            "Discount": get_element_text(driver, By.CSS_SELECTOR, ".savingsPercentage"),
            "Image URL": get_element_attribute(driver, By.CSS_SELECTOR, "#imgTagWrapperId img", "src"),
            "Description": get_element_text(driver, By.CSS_SELECTOR, "#feature-bullets")
        }

        # Extract data from tables (first_table, tech_specs, right_table, new_table)
        tables = {
            'first_table': '.a-normal.a-spacing-micro',
            'tech_specs': '#productDetails_techSpec_section_1',
            'right_table': '#productDetails_detailBullets_sections1',
            'new_table': 'ul.a-unordered-list.a-nostyle.a-vertical.a-spacing-none.detail-bullet-list'
        }

        for table_name, selector in tables.items():
            table = soup.select_one(selector)
            if table:
                if table_name == 'new_table':
                    items = table.find_all('li')
                    for item in items:
                        key_element = item.select_one('span.a-text-bold')
                        value_element = item.find(
                            'span', class_=lambda x: x != 'a-text-bold')
                        if key_element and value_element:
                            key = clean_text(
                                key_element.text.strip().replace(':', ''))
                            value = clean_text(value_element.text.strip())
                            value = remove_key_from_value(key, value)
                            product_data[key] = value
                else:
                    rows = table.find_all('tr')
                    for row in rows:
                        key_element = row.find(['th', 'td'])
                        value_element = row.find_all(
                            'td')[-1] if row.find_all('td') else None
                        if key_element and value_element:
                            key = clean_text(key_element.get_text(strip=True))
                            value = clean_text(
                                value_element.get_text(strip=True))
                            product_data[key] = value

        # Scrape reviews
        reviews = []
        review_cards = driver.find_elements(
            By.CSS_SELECTOR, "div[data-hook='review']")
        for review in review_cards[:5]:  # Limit to 5 reviews for performance
            reviewer_name = review.find_element(
                By.CSS_SELECTOR, "span.a-profile-name").text.strip()
            review_rating = review.find_element(By.CSS_SELECTOR, "i.a-icon-star span.a-icon-alt").get_attribute(
                "textContent").strip().replace("out of 5 stars", "")
            review_date = review.find_element(
                By.CSS_SELECTOR, "span.review-date").text.strip()
            review_text = review.find_element(
                By.CSS_SELECTOR, "span[data-hook='review-body']").text.strip()
            reviews.append({
                "Reviewer": reviewer_name,
                "Rating": review_rating,
                "Date": review_date,
                "Review": review_text
            })

        product_data['reviews'] = reviews
        return product_data
    finally:
        driver.quit()


def scrape_page_products(page_url):
    driver = create_driver()
    try:
        driver.get(page_url)
        random_sleep()
        soup = BeautifulSoup(driver.page_source, 'html.parser')

        # Extract product links
        product_links = soup.find_all(
            'a', class_='a-link-normal s-underline-text s-underline-link-text s-link-style a-text-normal')
        base_url = 'https://www.amazon.eg'
        list_products_links = [
            base_url + link.get('href') for link in product_links if link.get('href')]
        print(f"Products on the page {page_url}: {list_products_links}")

        # Check for the "Next" button
        try:
            next_button = driver.find_element(
                By.CSS_SELECTOR, "a.s-pagination-next")
            next_page_url = next_button.get_attribute('href')
            print(f"Next page URL: {next_page_url}")
        except Exception as e:
            print(f"No 'Next' button found or error occurred: {e}")
            next_page_url = None

        return list_products_links, next_page_url
    finally:
        driver.quit()


def scrape_all_products(start_page_url, num_pages=3):
    all_product_links = []
    current_page_url = start_page_url
    page_number = 1  # Initialize page number

    for _ in range(num_pages):
        print("="*100)
        print(f"Scraping page {page_number}: {current_page_url}")
        print("="*100)

        products, next_page = scrape_page_products(current_page_url)
        all_product_links.extend(products)

        # Print the number of product links found on the current page
        print(f"Page {page_number}: Found {len(products)} product links.")

        if not next_page:
            print("No more pages to scrape.")
            break

        current_page_url = next_page
        page_number += 1  # Increment page number

    print(f"Total product links found: {len(all_product_links)}")

    with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
        all_product_data = list(executor.map(
            scrape_product_data, all_product_links))

    product_df = pd.DataFrame(all_product_data)
    product_df.to_csv('Headphones.csv', index=False)


if __name__ == "__main__":
    start_time = time.time()  # Record the start time
    page_url = "https://www.amazon.eg/-/en/s?k=amazon+headphones&nis=6&qid=1725437692&ref=sr_pg_1"
    scrape_all_products(page_url)
    end_time = time.time()  # Record the end time
    elapsed_time = end_time - start_time  # Calculate elapsed time
    print(f"Script completed in {elapsed_time:.2f} seconds.")

""" 
Links we start from it:
1==> https://www.amazon.eg/-/en/s?k=amazon+headphones&nis=6&qid=1725437692&ref=sr_pg_1
"""
