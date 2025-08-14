import streamlit as st
import pandas as pd
import requests
from bs4 import BeautifulSoup
import time
import random
from urllib.parse import urljoin
import re
from datetime import datetime
import io

# Configure page
st.set_page_config(
    page_title="Amazon ASIN Price Scraper",
    page_icon="🛒",
    layout="wide"
)

class AmazonScraper:
    def __init__(self):
        self.session = requests.Session()
        self.base_url = "https://www.amazon.com/dp/"
        
        # Rotate user agents to appear more human-like
        self.user_agents = [
            'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
            'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
            'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:89.0) Gecko/20100101 Firefox/89.0',
        ]
        
    def get_page(self, asin):
        """Fetch Amazon product page with proper headers and rate limiting"""
        url = f"{self.base_url}{asin}/"
        
        headers = {
            'User-Agent': random.choice(self.user_agents),
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
            'Accept-Language': 'en-US,en;q=0.5',
            'Accept-Encoding': 'gzip, deflate',
            'Connection': 'keep-alive',
            'Upgrade-Insecure-Requests': '1',
        }
        
        try:
            # Random delay between 1-3 seconds to avoid detection
            time.sleep(random.uniform(1, 3))
            
            response = self.session.get(url, headers=headers, timeout=10)
            response.raise_for_status()
            return BeautifulSoup(response.content, 'html.parser'), url
        except Exception as e:
            st.error(f"Error fetching {asin}: {str(e)}")
            return None, url
    
    def clean_price(self, price_text):
        """Clean price text to extract numeric value"""
        if not price_text:
            return None
        
        # Convert to string if not already
        price_str = str(price_text).strip()
        
        # Method 1: Look for standard price patterns like $89.95, 89.95, etc.
        price_patterns = [
            r'\$?(\d{1,3}(?:,\d{3})*\.\d{2})',  # $1,234.56 or 1,234.56
            r'\$?(\d{1,3}(?:,\d{3})*)',         # $1,234 or 1,234 (whole numbers)
        ]
        
        for pattern in price_patterns:
            match = re.search(pattern, price_str)
            if match:
                clean_price = match.group(1).replace(',', '')
                try:
                    return float(clean_price)
                except:
                    continue
        
        # Method 2: If no standard pattern found, try to extract all digits and decimal
        digits_decimal = re.findall(r'\d+\.?\d*', price_str)
        if digits_decimal:
            try:
                # Take the first occurrence that looks like a price
                for candidate in digits_decimal:
                    if '.' in candidate and len(candidate.split('.')[1]) == 2:
                        return float(candidate)
                    elif '.' not in candidate and len(candidate) <= 6:  # Reasonable price length
                        return float(candidate)
            except:
                pass
        
        return price_str if price_str else None
    
    def extract_buybox_info(self, soup):
        """Extract buy box information"""
        buybox_data = {
            'buybox_price': None,
            'buybox_seller': None,
            'buybox_ships_from': None,
            'buybox_sold_by': None
        }
        
        # Enhanced price extraction - look for complete price structure
        price_found = False
        
        # Method 1: Look for complete price spans with decimal/fraction
        price_containers = soup.find_all('span', class_='a-price')
        for container in price_containers:
            if not price_found:
                # Look for whole + decimal + fraction structure
                whole_elem = container.find('span', class_='a-price-whole')
                fraction_elem = container.find('span', class_='a-price-fraction')
                
                if whole_elem:
                    whole_price = whole_elem.get_text().strip()
                    if fraction_elem:
                        fraction_price = fraction_elem.get_text().strip()
                        full_price = f"{whole_price}.{fraction_price}"
                    else:
                        full_price = whole_price
                    
                    buybox_data['buybox_price'] = self.clean_price(full_price)
                    price_found = True
                    break
        
        # Method 2: Fallback price selectors
        if not price_found:
            price_selectors = [
                '.a-price-whole',
                '#apex_desktop .a-price .a-price-whole',
                '#priceblock_dealprice',
                '#priceblock_pospromoprice',
                '.a-price .a-offscreen',
                '#priceDisplayInfoFeature .a-price .a-offscreen'
            ]
            
            for selector in price_selectors:
                price_elem = soup.select_one(selector)
                if price_elem:
                    buybox_data['buybox_price'] = self.clean_price(price_elem.get_text())
                    price_found = True
                    break
        
        # Enhanced seller information extraction
        seller_selectors = [
            '#merchantInfoFeature_feature_div a',
            '#sellerProfileTriggerId',
            '#merchant-info a',
            'a[href*="seller="]',
            '.tabular-buybox-text[data-feature-name="bylineInfo"] a'
        ]
        
        for selector in seller_selectors:
            seller_elem = soup.select_one(selector)
            if seller_elem:
                seller_text = seller_elem.get_text().strip()
                # Clean seller name
                seller_text = re.sub(r'^(by\s+|sold\s+by\s+)', '', seller_text, flags=re.IGNORECASE)
                buybox_data['buybox_seller'] = seller_text
                break
        
        # Enhanced fulfillment info extraction
        fulfillment_containers = [
            '#merchantInfoFeature_feature_div',
            '#tabular-buybox',
            '.tabular-buybox-text',
            '#merchant-info'
        ]
        
        for container_selector in fulfillment_containers:
            fulfillment_elem = soup.select_one(container_selector)
            if fulfillment_elem:
                text = fulfillment_elem.get_text()
                
                # Ships from
                ships_patterns = [
                    r'Ships from\s+([^.\n]+)',
                    r'Shipped from\s+([^.\n]+)',
                    r'Ships from:\s*([^.\n]+)'
                ]
                for pattern in ships_patterns:
                    ships_match = re.search(pattern, text, re.IGNORECASE)
                    if ships_match and not buybox_data['buybox_ships_from']:
                        buybox_data['buybox_ships_from'] = ships_match.group(1).strip()
                        break
                
                # Sold by
                sold_patterns = [
                    r'Sold by\s+([^.\n]+)',
                    r'Sold by:\s*([^.\n]+)'
                ]
                for pattern in sold_patterns:
                    sold_match = re.search(pattern, text, re.IGNORECASE)
                    if sold_match and not buybox_data['buybox_sold_by']:
                        buybox_data['buybox_sold_by'] = sold_match.group(1).strip()
                        break
                
                if buybox_data['buybox_ships_from'] and buybox_data['buybox_sold_by']:
                    break
        
        return buybox_data
    
    def extract_other_sellers(self, soup, asin):
        """Extract other sellers information by following the offer-listing page"""
        sellers_data = []
        
        # First, look for the "Other Sellers on Amazon" link
        offer_link = None
        
        # Look for the link that leads to offer-listing page
        offer_selectors = [
            'a[href*="offer-listing"]',
            'a[href*="/gp/offer-listing/"]',
            '#aod-ingress-link',
            'a[id="aod-ingress-link"]'
        ]
        
        for selector in offer_selectors:
            link_elem = soup.select_one(selector)
            if link_elem and link_elem.get('href'):
                offer_link = link_elem.get('href')
                if offer_link.startswith('/'):
                    offer_link = 'https://www.amazon.com' + offer_link
                break
        
        # If no direct link found, construct the offers URL
        if not offer_link:
            offer_link = f"https://www.amazon.com/gp/offer-listing/{asin}/ref=dp_olp_ALL_mbc?ie=UTF8&condition=ALL"
        
        st.info(f"Fetching additional sellers from: {offer_link}")
        
        try:
            # Fetch the offers page
            time.sleep(random.uniform(1, 2))  # Be respectful
            offers_soup, _ = self.get_page_direct(offer_link)
            
            if offers_soup:
                # Multiple selectors for finding offer containers
                offer_containers = []
                
                # Try different container selectors
                container_selectors = [
                    'div[data-aod-atc-action]',  # Modern Amazon structure
                    'div.a-row.a-spacing-mini.olp-offer-row',  # Traditional structure
                    'div.olp-offer-row',
                    'div[class*="olp-offer"]',
                    'div.a-section.a-spacing-small.olp-offer'
                ]
                
                for selector in container_selectors:
                    containers = offers_soup.select(selector)
                    if containers:
                        offer_containers = containers
                        st.info(f"Found {len(containers)} sellers using selector: {selector}")
                        break
                
                # If still no containers, try broader search
                if not offer_containers:
                    # Look for any divs that contain price information
                    all_divs = offers_soup.find_all('div')
                    for div in all_divs:
                        if div.find('span', class_='a-price') or div.find('span', string=re.compile(r'\$\d+')):
                            offer_containers.append(div)
                    
                    if offer_containers:
                        st.info(f"Found {len(offer_containers)} potential seller containers through broad search")
                
                # Process each seller container
                for i, container in enumerate(offer_containers):
                    if i >= 20:  # Limit to first 20 sellers to avoid excessive processing
                        break
                        
                    seller_data = {}
                    container_text = container.get_text()
                    
                    # Extract price with enhanced methods
                    price_found = False
                    
                    # Method 1: Look for a-offscreen price (most reliable)
                    offscreen_price = container.find('span', class_='a-offscreen')
                    if offscreen_price:
                        price_text = offscreen_price.get_text().strip()
                        cleaned_price = self.clean_price(price_text)
                        if cleaned_price:
                            seller_data['price'] = cleaned_price
                            price_found = True
                    
                    # Method 2: Construct from price parts
                    if not price_found:
                        price_container = container.find('span', class_='a-price')
                        if price_container:
                            whole_elem = price_container.find('span', class_='a-price-whole')
                            fraction_elem = price_container.find('span', class_='a-price-fraction')
                            decimal_elem = price_container.find('span', class_='a-price-decimal')
                            
                            if whole_elem:
                                whole_text = whole_elem.get_text().strip().replace(',', '')
                                if fraction_elem:
                                    fraction_text = fraction_elem.get_text().strip()
                                    if decimal_elem:
                                        decimal_text = decimal_elem.get_text().strip()
                                        full_price = f"{whole_text}{decimal_text}{fraction_text}"
                                    else:
                                        full_price = f"{whole_text}.{fraction_text}"
                                else:
                                    full_price = whole_text
                                
                                cleaned_price = self.clean_price(full_price)
                                if cleaned_price:
                                    seller_data['price'] = cleaned_price
                                    price_found = True
                    
                    # Method 3: Regex fallback for price
                    if not price_found:
                        price_matches = re.findall(r'\$(\d{1,3}(?:,\d{3})*(?:\.\d{2})?)', container_text)
                        if price_matches:
                            seller_data['price'] = self.clean_price(price_matches[0])
                            price_found = True
                    
                    # Extract seller name with multiple approaches
                    seller_name_found = False
                    
                    # Look for seller profile links
                    seller_links = container.find_all('a', href=re.compile(r'seller='))
                    for link in seller_links:
                        seller_name = link.get_text().strip()
                        if seller_name and seller_name.lower() not in ['amazon', 'amazon.com']:
                            seller_name = re.sub(r'^(by\s+)', '', seller_name, flags=re.IGNORECASE)
                            seller_data['seller_name'] = seller_name
                            seller_name_found = True
                            break
                    
                    # Fallback: look for seller mentions in text
                    if not seller_name_found:
                        seller_patterns = [
                            r'Sold by\s+([^.\n]+?)(?:\s|$)',
                            r'Ships from and sold by\s+([^.\n]+?)(?:\s|$)',
                            r'by\s+([^.\n]+?)(?:\s|$)'
                        ]
                        
                        for pattern in seller_patterns:
                            match = re.search(pattern, container_text, re.IGNORECASE)
                            if match:
                                seller_name = match.group(1).strip()
                                if seller_name and len(seller_name) > 2:
                                    seller_data['seller_name'] = seller_name
                                    seller_name_found = True
                                    break
                    
                    # Extract condition
                    condition_keywords = ['New', 'Used', 'Refurbished', 'Collectible', 'Renewed']
                    for keyword in condition_keywords:
                        if keyword.lower() in container_text.lower():
                            seller_data['condition'] = keyword
                            break
                    
                    # Extract shipping information
                    shipping_patterns = [
                        r'(\$\d+\.\d{2}\s+shipping)',
                        r'(FREE\s+(?:Shipping|delivery))',
                        r'(\+\s*\$\d+\.\d{2}\s+shipping)',
                        r'(Prime\s+FREE\s+Delivery)'
                    ]
                    
                    for pattern in shipping_patterns:
                        match = re.search(pattern, container_text, re.IGNORECASE)
                        if match:
                            seller_data['shipping'] = match.group(1).strip()
                            break
                    
                    # Extract fulfillment info
                    # Ships from
                    ships_match = re.search(r'Ships from\s+([^.\n]+)', container_text, re.IGNORECASE)
                    if ships_match:
                        seller_data['ships_from'] = ships_match.group(1).strip()
                    
                    # Sold by (different from seller_name, this is fulfillment info)
                    sold_match = re.search(r'Sold by\s+([^.\n]+)', container_text, re.IGNORECASE)
                    if sold_match:
                        seller_data['sold_by'] = sold_match.group(1).strip()
                    
                    # Only add seller if we found meaningful data (price OR seller name)
                    if seller_data.get('price') or seller_data.get('seller_name'):
                        sellers_data.append(seller_data)
                        st.success(f"✓ Seller {len(sellers_data)}: {seller_data.get('seller_name', 'Unknown')} - ${seller_data.get('price', 'N/A')} - {seller_data.get('condition', 'N/A')}")
                    
                st.info(f"Successfully extracted {len(sellers_data)} sellers total")
                
        except Exception as e:
            st.error(f"Error fetching additional seller data for {asin}: {str(e)}")
            import traceback
            st.error(f"Traceback: {traceback.format_exc()}")
        
        return sellers_data
    
    def get_page_direct(self, url):
        """Direct URL fetch for offers page"""
        headers = {
            'User-Agent': random.choice(self.user_agents),
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
            'Accept-Language': 'en-US,en;q=0.5',
        }
        
        try:
            time.sleep(random.uniform(1, 2))
            response = self.session.get(url, headers=headers, timeout=10)
            response.raise_for_status()
            return BeautifulSoup(response.content, 'html.parser'), url
        except:
            return None, url
    
    def scrape_asin(self, asin):
        """Main scraping function for a single ASIN"""
        soup, url = self.get_page(asin)
        
        if not soup:
            return [{
                'ASIN': asin,
                'Title': 'Error: Could not fetch page',
                'URL': url,
                'Status': 'Error',
                'buybox_price': None,
                'buybox_seller': None,
                'buybox_ships_from': None,
                'buybox_sold_by': None,
                'seller_type': 'buybox',
                'seller_name': None,
                'seller_price': None,
                'seller_condition': None,
                'seller_shipping': None,
                'seller_ships_from': None,
                'seller_sold_by': None
            }]
        
        # Enhanced title extraction
        title = None
        title_selectors = [
            'span#productTitle',
            '#productTitle',
            'h1.a-size-large',
            'h1 span',
            'h1',
            '.product-title',
            '[data-automation-id="product-title"]'
        ]
        
        for selector in title_selectors:
            title_elem = soup.select_one(selector)
            if title_elem:
                title = title_elem.get_text().strip()
                if title:  # Make sure it's not empty
                    break
        
        if not title:
            title = 'Title not found'
        
        # Check if product is available
        unavailable_indicators = [
            'Currently unavailable',
            'This item is not available',
            'Page Not Found',
            'Sorry, we just ran out',
            'Out of stock'
        ]
        
        page_text = soup.get_text()
        is_available = not any(indicator in page_text for indicator in unavailable_indicators)
        
        # Extract buy box info
        buybox_data = self.extract_buybox_info(soup)
        
        # Extract other sellers
        other_sellers = self.extract_other_sellers(soup, asin)
        
        # Prepare results
        results = []
        
        # Add buy box row
        base_data = {
            'ASIN': asin,
            'Title': title,
            'URL': url,
            'Status': 'Available' if is_available else 'Unavailable',
            **buybox_data,
            'seller_type': 'buybox',
            'seller_name': buybox_data.get('buybox_seller'),
            'seller_price': buybox_data.get('buybox_price'),
            'seller_condition': 'New',  # Buy box is typically new
            'seller_shipping': None,
            'seller_ships_from': buybox_data.get('buybox_ships_from'),
            'seller_sold_by': buybox_data.get('buybox_sold_by')
        }
        results.append(base_data)
        
        # Add other sellers rows
        for i, seller in enumerate(other_sellers):
            seller_row = base_data.copy()
            seller_row.update({
                'seller_type': f'other_seller_{i+1}',
                'seller_name': seller.get('seller_name'),
                'seller_price': seller.get('price'),
                'seller_condition': seller.get('condition', 'Unknown'),
                'seller_shipping': seller.get('shipping'),
                'seller_ships_from': seller.get('ships_from'),
                'seller_sold_by': seller.get('sold_by')
            })
            results.append(seller_row)
        
        return results

def main():
    st.title("🛒 Amazon ASIN Price Scraper")
    st.markdown("Extract detailed pricing and seller information from Amazon product pages")
    
    # Warning about ToS
    with st.expander("⚠️ Important Usage Guidelines"):
        st.warning("""
        **Please read carefully:**
        - This tool is for educational and research purposes
        - Respect Amazon's Terms of Service and robots.txt
        - Use reasonable delays between requests (built-in)
        - Don't overload Amazon's servers with excessive requests
        - Consider Amazon's API alternatives for commercial use
        - You are responsible for complying with all applicable terms and laws
        """)
    
    # Initialize scraper
    if 'scraper' not in st.session_state:
        st.session_state.scraper = AmazonScraper()
    
    # Input methods
    st.subheader("📥 Input ASINs")
    
    col1, col2 = st.columns(2)
    
    with col1:
        st.markdown("**Option 1: Upload Excel/CSV File**")
        uploaded_file = st.file_uploader(
            "Choose file (Excel or CSV)",
            type=['xlsx', 'xls', 'csv'],
            help="File should contain ASINs in a column named 'ASIN' or 'asin'"
        )
        
        asins_from_file = []
        if uploaded_file:
            try:
                if uploaded_file.name.endswith('.csv'):
                    df = pd.read_csv(uploaded_file)
                else:
                    df = pd.read_excel(uploaded_file)
                
                # Look for ASIN column (case insensitive)
                asin_col = None
                for col in df.columns:
                    if col.lower() in ['asin', 'asins']:
                        asin_col = col
                        break
                
                if asin_col:
                    asins_from_file = df[asin_col].dropna().astype(str).tolist()
                    st.success(f"Loaded {len(asins_from_file)} ASINs from file")
                else:
                    st.error("Could not find 'ASIN' column in uploaded file")
                    
            except Exception as e:
                st.error(f"Error reading file: {str(e)}")
    
    with col2:
        st.markdown("**Option 2: Paste ASINs**")
        manual_asins = st.text_area(
            "Paste ASINs (one per line)",
            height=150,
            placeholder="B0BVGTZCLB\nB01234ABCD\nB09876WXYZ"
        )
        
        asins_from_text = []
        if manual_asins:
            asins_from_text = [asin.strip() for asin in manual_asins.split('\n') if asin.strip()]
    
    # Combine ASINs
    all_asins = list(set(asins_from_file + asins_from_text))  # Remove duplicates
    
    if all_asins:
        st.info(f"Total unique ASINs to process: {len(all_asins)}")
        
        # Rate limiting settings
        st.subheader("⚙️ Scraping Settings")
        
        col1, col2 = st.columns(2)
        with col1:
            delay_min = st.slider("Min delay between requests (seconds)", 1, 5, 2)
        with col2:
            delay_max = st.slider("Max delay between requests (seconds)", 3, 10, 5)
        
        # Process ASINs
        if st.button("🚀 Start Scraping", type="primary"):
            
            progress_bar = st.progress(0)
            status_text = st.empty()
            
            all_results = []
            
            for i, asin in enumerate(all_asins):
                status_text.text(f"Processing ASIN {i+1}/{len(all_asins)}: {asin}")
                
                # Update delay settings
                st.session_state.scraper.delay_min = delay_min
                st.session_state.scraper.delay_max = delay_max
                
                results = st.session_state.scraper.scrape_asin(asin)
                all_results.extend(results)
                
                progress_bar.progress((i + 1) / len(all_asins))
                
                # Add random delay between requests
                if i < len(all_asins) - 1:  # Don't delay after last item
                    delay = random.uniform(delay_min, delay_max)
                    time.sleep(delay)
            
            status_text.text("Processing complete!")
            
            # Create DataFrame
            df_results = pd.DataFrame(all_results)
            
            # Display results
            st.subheader("📊 Results")
            st.dataframe(df_results, use_container_width=True)
            
            # Download options
            st.subheader("💾 Download Results")
            
            col1, col2 = st.columns(2)
            
            with col1:
                # CSV download
                csv = df_results.to_csv(index=False)
                st.download_button(
                    label="Download as CSV",
                    data=csv,
                    file_name=f"amazon_scrape_results_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv",
                    mime="text/csv"
                )
            
            with col2:
                # Excel download
                buffer = io.BytesIO()
                with pd.ExcelWriter(buffer, engine='openpyxl') as writer:
                    df_results.to_excel(writer, index=False, sheet_name='Amazon_Data')
                
                st.download_button(
                    label="Download as Excel",
                    data=buffer.getvalue(),
                    file_name=f"amazon_scrape_results_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx",
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
                )
            
            # Summary stats
            st.subheader("📈 Summary")
            col1, col2, col3 = st.columns(3)
            
            with col1:
                st.metric("Total ASINs Processed", len(all_asins))
            
            with col2:
                available_count = len([r for r in all_results if r['Status'] == 'Available'])
                st.metric("Available Products", available_count)
            
            with col3:
                total_sellers = len([r for r in all_results if r['seller_type'] != 'buybox'])
                st.metric("Other Sellers Found", total_sellers)
    
    else:
        st.info("Please upload a file or paste ASINs to get started.")

if __name__ == "__main__":
    main()