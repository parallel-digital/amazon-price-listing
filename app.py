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
        # Remove currency symbols and extra whitespace
        price = re.sub(r'[^\d.,]', '', price_text.strip())
        # Handle cases like "1,234.56"
        price = price.replace(',', '')
        try:
            return float(price)
        except:
            return price_text.strip()
    
    def extract_buybox_info(self, soup):
        """Extract buy box information"""
        buybox_data = {
            'buybox_price': None,
            'buybox_seller': None,
            'buybox_ships_from': None,
            'buybox_sold_by': None
        }
        
        # Try to find price in buy box
        price_selectors = [
            '.a-price.a-text-price.a-size-medium.a-color-base .a-price-whole',
            '.a-price-whole',
            '#apex_desktop .a-price .a-price-whole',
            '#priceblock_dealprice',
            '#priceblock_pospromoprice'
        ]
        
        for selector in price_selectors:
            price_elem = soup.select_one(selector)
            if price_elem:
                buybox_data['buybox_price'] = self.clean_price(price_elem.get_text())
                break
        
        # Try to find seller information
        seller_selectors = [
            '#merchantInfoFeature_feature_div a',
            '#sellerProfileTriggerId',
            '#merchant-info a'
        ]
        
        for selector in seller_selectors:
            seller_elem = soup.select_one(selector)
            if seller_elem:
                buybox_data['buybox_seller'] = seller_elem.get_text().strip()
                break
        
        # Ships from and sold by info
        fulfillment_elem = soup.select_one('#merchantInfoFeature_feature_div')
        if fulfillment_elem:
            text = fulfillment_elem.get_text()
            if 'Ships from' in text:
                ships_match = re.search(r'Ships from\s+([^.]+)', text)
                if ships_match:
                    buybox_data['buybox_ships_from'] = ships_match.group(1).strip()
            
            if 'Sold by' in text:
                sold_match = re.search(r'Sold by\s+([^.]+)', text)
                if sold_match:
                    buybox_data['buybox_sold_by'] = sold_match.group(1).strip()
        
        return buybox_data
    
    def extract_other_sellers(self, soup, asin):
        """Extract other sellers information"""
        sellers_data = []
        
        # Look for "Other Sellers on Amazon" section
        other_sellers_section = soup.find('div', {'id': 'olp-upd-new-used-carousel'}) or \
                               soup.find('div', {'data-feature-name': 'olp-carousel'}) or \
                               soup.find('div', string=re.compile('Other Sellers on Amazon', re.I))
        
        if other_sellers_section:
            # Find seller containers
            seller_containers = other_sellers_section.find_all('div', class_=re.compile('olp-card|offer-listing'))
            
            for container in seller_containers:
                seller_data = {}
                
                # Price
                price_elem = container.find('span', class_=re.compile('a-price-whole|price'))
                if price_elem:
                    seller_data['price'] = self.clean_price(price_elem.get_text())
                
                # Seller name
                seller_elem = container.find('a', href=re.compile('seller=')) or \
                             container.find('span', string=re.compile('by '))
                if seller_elem:
                    seller_data['seller_name'] = seller_elem.get_text().strip()
                
                # Condition
                condition_elem = container.find('span', string=re.compile('New|Used|Refurbished', re.I))
                if condition_elem:
                    seller_data['condition'] = condition_elem.get_text().strip()
                
                # Shipping info
                shipping_elem = container.find('span', string=re.compile('shipping|delivery', re.I))
                if shipping_elem:
                    seller_data['shipping'] = shipping_elem.get_text().strip()
                
                if seller_data:  # Only add if we found some data
                    sellers_data.append(seller_data)
        
        # If no sellers found in carousel, try the "See All Buying Options" approach
        if not sellers_data:
            # This might require a separate request to the offers page
            offers_url = f"https://www.amazon.com/gp/offer-listing/{asin}/"
            try:
                offers_soup, _ = self.get_page_direct(offers_url)
                if offers_soup:
                    offer_rows = offers_soup.find_all('div', class_=re.compile('olp-offer'))
                    for row in offer_rows:
                        seller_data = {}
                        
                        # Price
                        price_elem = row.find('span', class_='a-price-whole')
                        if price_elem:
                            seller_data['price'] = self.clean_price(price_elem.get_text())
                        
                        # Seller
                        seller_elem = row.find('a', href=re.compile('seller='))
                        if seller_elem:
                            seller_data['seller_name'] = seller_elem.get_text().strip()
                        
                        # Condition
                        condition_elem = row.find('span', class_='olp-condition-text')
                        if condition_elem:
                            seller_data['condition'] = condition_elem.get_text().strip()
                        
                        if seller_data:
                            sellers_data.append(seller_data)
                            
            except Exception as e:
                st.warning(f"Could not fetch additional seller data for {asin}: {str(e)}")
        
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
                'seller_shipping': None
            }]
        
        # Extract title
        title_elem = soup.find('span', {'id': 'productTitle'}) or soup.find('h1')
        title = title_elem.get_text().strip() if title_elem else 'Title not found'
        
        # Check if product is available
        unavailable_indicators = [
            'Currently unavailable',
            'This item is not available',
            'Page Not Found'
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
            'seller_type': 'buybox'
        }
        results.append(base_data)
        
        # Add other sellers rows
        for i, seller in enumerate(other_sellers):
            seller_row = base_data.copy()
            seller_row.update({
                'seller_type': f'other_seller_{i+1}',
                'seller_name': seller.get('seller_name'),
                'seller_price': seller.get('price'),
                'seller_condition': seller.get('condition'),
                'seller_shipping': seller.get('shipping')
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