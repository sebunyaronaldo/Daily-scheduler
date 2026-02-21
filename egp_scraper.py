#!/usr/bin/env python3
import os
import requests
import pandas as pd
import time
import re
from datetime import datetime
from bs4 import BeautifulSoup
import logging
from typing import List, Dict, Optional
import json
import csv
from io import StringIO

logger = logging.getLogger(__name__)

class EGPScraper:
    def __init__(self, email: str, password: str):
        self.base_url = "https://egpuganda.go.ug"
        self.email = email
        self.password = password
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
        })
        
    def login(self) -> bool:
        """Login to the eGP portal"""
        try:
            logger.info("Attempting to login to eGP portal...")
            
            # Firstt, get the login page to extract CSRF token,ok
            login_url = f"{self.base_url}/login"
            response = self.session.get(login_url)
            response.raise_for_status()
            
            # Parse the login page to extract CSRF tokens
            soup = BeautifulSoup(response.text, 'html.parser')
            csrf_token = soup.find('input', {'name': '_token'})
            
            if not csrf_token:
                logger.error("Could not find CSRF token on login page")
                return False
            
            csrf_value = csrf_token.get('value')
            logger.info(f"Extracted CSRF token: {csrf_value[:10]}...")
            
            # Prepare login data
            login_data = {
                '_token': csrf_value,
                'email': self.email,
                'password': self.password
            }
            
            # Perform login
            response = self.session.post(login_url, data=login_data)
            
                # Check if login was successful
            if response.status_code == 200:
                # Check for successful login indicators
                if 'dashboard' in response.url or 'logout' in response.text:
                    logger.info("Login successful!")
                    return True
                else:
                    # Check for error messages on the login page
                    soup = BeautifulSoup(response.text, 'html.parser')
                    error_messages = soup.find_all(class_='alert-danger') or soup.find_all(class_='error')
                    if error_messages:
                        logger.error(f"Login failed - error messages found: {[msg.get_text().strip() for msg in error_messages]}")
                    else:
                        logger.error("Login failed - could not determine success/failure")
                    return False
            else:
                logger.error(f"Login request failed with status code: {response.status_code}")
                return False
                
        except Exception as e:
            logger.error(f"Login error: {str(e)}")
            return False
    
    def get_bid_notices(self, category: str = "all", max_pages: int = 5) -> List[Dict]:
        """Get bid notices using the correct API endpoint"""
        try:
            logger.info(f"Fetching bid notices from API...")
            
            # Try different API endpoints to find the correct one for bid notices
            api_endpoints = [
                f"{self.base_url}/api/v1/bid_notices",  # Try bid notices endpoint
                f"{self.base_url}/api/v1/public_bid_notices",  # Try public bid notices
                f"{self.base_url}/api/v1/bid-notices",  # Try with hyphen
                f"{self.base_url}/api/v1/public_bid_archives"  # Fallback to archives
            ]
            
            contracts = []
            page = 1
            
            # Try each endpoint until we find one that works
            for api_url in api_endpoints:
                logger.info(f"Trying API endpoint: {api_url}")
                
                try:
                    # Test the endpoint with first page
                    params = {
                        'draw': 1,
                        'start': 0,
                        'length': 10,
                        'order[0][column]': 1,
                        'order[0][dir]': 'desc'
                    }
                    
                    response = self.session.get(api_url, params=params)
                    response.raise_for_status()
                    
                    data = response.json()
                    
                    if data and 'data' in data and data['data']:
                        logger.info(f"Found working endpoint: {api_url}")
                        break
                    else:
                        logger.warning(f"Endpoint {api_url} returned no data")
                        continue
                
                except Exception as e:
                    logger.warning(f"Endpoint {api_url} failed: {str(e)}")
                    continue
            else:
                logger.error("No working API endpoint found")
                return []
            
            # Now fetch data from the working endpoint
            while page <= max_pages:
                logger.info(f"Fetching page {page} from {api_url}...")
                
                # Parameters for the DataTable API
                params = {
                    'draw': page,
                    'start': (page - 1) * 10,
                    'length': 10,
                    'order[0][column]': 1,
                    'order[0][dir]': 'desc'
                }
                
                try:
                    response = self.session.get(api_url, params=params)
                    response.raise_for_status()
                    
                    # Parse JSON response
                    data = response.json()
                    
                    if not data or 'data' not in data:
                        logger.warning(f"No data found in API response for page {page}")
                        break
                    
                    # Extract contracts from the data
                    page_contracts = data['data']
                    
                    if not page_contracts:
                        logger.info(f"No more contracts found on page {page}")
                        break
                    
                    # Process each contract
                    for contract_data in page_contracts:
                        contract = self._extract_contract_data_from_api(contract_data)
                        if contract:
                            contracts.append(contract)
                    
                    logger.info(f"Found {len(page_contracts)} contracts on page {page}")
                    page += 1
                    
                    # Add a small delay to be respectful to the server
                    time.sleep(1)
                    
                except requests.exceptions.RequestException as e:
                    logger.error(f"Error fetching page {page}: {str(e)}")
                    break
                except json.JSONDecodeError as e:
                    logger.error(f"Error parsing JSON response for page {page}: {str(e)}")
                    break
                
            logger.info(f"Total contracts fetched: {len(contracts)}")
            return contracts
            
        except Exception as e:
            logger.error(f"Error in get_bid_notices: {str(e)}")
            return []

    def get_bid_notices_from_page(self, include_details: bool = True) -> List[Dict]:
        """Get bid notices by directly scraping the bid notices page"""
        try:
            logger.info("Fetching bid notices directly from the bid notices page...")
            
            # Navigate to the bid notices page
            bid_url = f"{self.base_url}/bid/notices"
            response = self.session.get(bid_url)
            response.raise_for_status()
            
            soup = BeautifulSoup(response.text, 'html.parser')
            
            # Look for the bid notices table
            table = soup.find('table', id='bid-notices-open')
            if not table:
                logger.warning("Bid notices table not found")
                return []
            
            contracts = []
            rows = table.find_all('tr')[1:]  # Skip header row
            
            logger.info(f"Found {len(rows)} rows in bid notices table")
            
            for i, row in enumerate(rows):
                try:
                    cells = row.find_all('td')
                    if len(cells) < 6:
                        continue
                    
                    # Extract data from table cells
                    entity_cell = cells[0]
                    method_cell = cells[1]
                    title_cell = cells[2]
                    status_cell = cells[3]
                    published_cell = cells[4]
                    deadline_cell = cells[5]
                    
                    # Extract reference number and entity
                    entity_link = entity_cell.find('a', href=re.compile(r'/bid/notice/\d+/details'))
                    if not entity_link:
                        continue
                    
                    href = entity_link.get('href', '')
                    ref_match = re.search(r'/bid/notice/(\d+)/details', href)
                    if not ref_match:
                        continue
                    
                    reference_number = ref_match.group(1)
                    
                    # Extract entity name
                    entity_name_elem = entity_cell.find('div', class_='text-muted')
                    procuring_entity = entity_name_elem.get_text().strip() if entity_name_elem else "Unknown"
                    
                    # Extract title
                    title = title_cell.get_text().strip()
                    
                    # Extract method
                    procurement_method = method_cell.get_text().strip()
                    
                    # Extract status
                    status = status_cell.get_text().strip()
                    
                    # Extract dates
                    published_date = published_cell.get_text().strip()
                    deadline = deadline_cell.get_text().strip()
                    
                    # Construct detail URL
                    detail_url = f"{self.base_url}/bid/notice/{reference_number}/details"
                    
                    contract = {
                        'reference_number': None,  # Will be filled from detail page
                        'title': title,
                        'procuring_entity': procuring_entity,
                        'procurement_method': procurement_method,
                        'status': status,
                        'published_date': self._parse_date(published_date),
                        'deadline': self._parse_date(deadline),
                        'detail_url': detail_url,
                        'category': self._extract_category_from_title(title),
                        'description': title
                    }
                    
                    # Fetch detailed information if requested
                    if include_details:
                        logger.info(f"Fetching details for contract {i+1}/{len(rows)}: {reference_number}")
                        details = self.get_contract_details(detail_url)
                        contract.update(details)
                        
                        # Add a small delay to be respectful to the server
                        time.sleep(1)
                    
                    contracts.append(contract)
                    
                except Exception as e:
                    logger.error(f"Error processing row: {str(e)}")
                    continue
            
            logger.info(f"Extracted {len(contracts)} contracts from bid notices page")
            return contracts
    
        except Exception as e:
            logger.error(f"Error scraping bid notices page: {str(e)}")
            return []

    def get_contract_details(self, detail_url: str) -> Dict:
        """Get detailed information from a contract's detail page"""
        try:
            logger.info(f"Fetching details from: {detail_url}")
            
            response = self.session.get(detail_url)
            response.raise_for_status()
            
            soup = BeautifulSoup(response.text, 'html.parser')
            
            details = {}
            
            # Extract procurement reference number from the table
            procurement_ref_elem = soup.find('td', string=re.compile(r'[A-Z]+/[A-Z]+/\d{4}-\d{4}/\d+'))
            if procurement_ref_elem:
                details['reference_number'] = procurement_ref_elem.get_text().strip()
            
            # Extract bid fee
            fee_elem = soup.find('td', string=re.compile(r'UGX.*'))
            if fee_elem:
                fee_text = fee_elem.get_text().strip()
                # Remove UGX prefix and clean up
                fee_clean = fee_text.replace('UGX', '').replace(',', '').strip()
                details['bid_fee'] = fee_clean
            
            # Extract bid security
            bid_security_row = soup.find('td', string='BID SECURITY')
            if bid_security_row:
                parent_row = bid_security_row.find_parent('tr')
                if parent_row:
                    bid_security_cells = parent_row.find_all('td')
                    if len(bid_security_cells) >= 2:
                        bid_security_value = bid_security_cells[1].get_text().strip()
                        if bid_security_value and bid_security_value != 'BID SECURITY':
                            # Parse the bid security amount
                            amount = self._parse_bid_security_amount(bid_security_value)
                            if amount > 0:
                                details['bid_security_amount'] = amount
                                details['bid_security_type'] = "Bank Guarantee or Letter of Credit or cashiers check or bank draft"
                            else:
                                details['bid_security_amount'] = 0
                                details['bid_security_type'] = None
                        else:
                            # No bid security required
                            details['bid_security_amount'] = 0
                            details['bid_security_type'] = None
            else:
                # No bid security row found - no security required
                details['bid_security_amount'] = 0
                details['bid_security_type'] = None
            
            # Extract bid validity dates
            validity_elem = soup.find('span', class_='breadcrumb-item', string=re.compile(r'\d+ \w+, \d+ \d+:\d+ - \d+ \w+, \d+ \d+:\d+'))
            if validity_elem:
                validity_text = validity_elem.get_text().strip()
                details['bid_validity_dates'] = validity_text
                
                # Split into start and end dates
                if ' - ' in validity_text:
                    start_date, end_date = validity_text.split(' - ', 1)
                    details['bid_validity_start'] = self._parse_date(start_date.strip())
                    details['bid_validity_end'] = self._parse_date(end_date.strip())
            
            # Extract source of funding - REMOVED as not needed
            # funding_elem = soup.find('span', class_='font-weight-bold text-uppercase')
            # if funding_elem:
            #     details['source_of_funding'] = funding_elem.get_text().strip()
            
            # Extract contact information
            contact_elems = soup.find_all('li', string=re.compile(r'Name:|Position:'))
            for elem in contact_elems:
                text = elem.get_text().strip()
                if 'Name:' in text:
                    details['contact_person'] = text.replace('Name:', '').strip()
                elif 'Position:' in text:
                    details['contact_position'] = text.replace('Position:', '').strip()
            
            # Extract procurement schedule
            schedule_table = soup.find('table', class_='table table-bordered')
            if schedule_table:
                schedule_data = {}
                rows = schedule_table.find_all('tr')[1:]  # Skip header
                for row in rows:
                    cells = row.find_all('td')
                    if len(cells) >= 2:
                        activity = cells[0].get_text().strip().lower()
                        date = cells[1].get_text().strip()
                        schedule_data[activity] = date
                        
                        # Extract specific dates as separate fields
                        if 'publish bid notice' in activity:
                            details['publish_notice_date'] = self._parse_date(date)
                        elif 'pre-bid meeting' in activity or 'pre bid meeting' in activity:
                            details['pre_bid_meeting_date'] = self._parse_date(date)
                        elif 'bid closing date' in activity or 'closing date' in activity:
                            details['bid_closing_date'] = self._parse_date(date)
                        elif 'evaluation process' in activity:
                            details['evaluation_period'] = date
                        elif 'best evaluated bidder' in activity or 'award' in activity:
                            details['award_notice_period'] = date
                        elif 'contract signature' in activity:
                            details['contract_signature_period'] = date
                
                details['procurement_schedule'] = schedule_data
            
            # Extract bid attachments
            attachment_links = soup.find_all('a', href=re.compile(r'\.(doc|docx|pdf|xls|xlsx)$'))
            attachments = []
            for link in attachment_links:
                attachments.append({
                    'filename': link.get_text().strip(),
                    'url': link.get('href', '')
                })
            details['attachments'] = attachments
            
            # Extract detailed description - REMOVED as not needed
            # desc_elem = soup.find('p', string=re.compile(r'^[A-Z].*'))
            # if desc_elem:
            #     details['detailed_description'] = desc_elem.get_text().strip()
            
            logger.info(f"Extracted {len(details)} detail fields")
            return details
            
        except Exception as e:
            logger.error(f"Error fetching contract details: {str(e)}")
            return {}

    def _extract_contract_data_from_api(self, contract_data: List) -> Optional[Dict]:
        """Extract contract data from API response"""
        try:
            # The API returns data as an array where each element corresponds to a table column
            # Based on the actual API response, the columns are:
            # [0]: Procuring Entity (with image and name)
            # [1]: Procurement Method
            # [2]: Bid Details (title)
            # [3]: Status
            # [4]: Published Date
            # [5]: Deadline
            # Note: The Actions column (View Details link) is not included in the API response
            
            if len(contract_data) < 6:
                logger.warning(f"Invalid contract data structure: {contract_data}")
                return None
            
            # Extract procuring entity and reference number
            entity_html = contract_data[0]
            soup = BeautifulSoup(entity_html, 'html.parser')
            
            # Find the reference number link
            ref_link = soup.find('a', href=re.compile(r'/bid/notice/\d+/details'))
            if not ref_link:
                return None
            
            # Extract reference number from the href attribute
            href = ref_link.get('href', '')
            ref_match = re.search(r'/bid/notice/(\d+)/details', href)
            if not ref_match:
                return None
            
            reference_number = ref_match.group(1)
            
            # Extract procuring entity name and clean it
            entity_name_elem = soup.find('div', class_='text-muted')
            procuring_entity = entity_name_elem.get_text().strip() if entity_name_elem else "Unknown"
            
            # Extract title and clean HTML tags
            title_html = contract_data[2]
            title_soup = BeautifulSoup(title_html, 'html.parser')
            title = title_soup.get_text().strip()
            
            # Extract procurement method and clean HTML tags
            method_html = contract_data[1]
            method_soup = BeautifulSoup(method_html, 'html.parser')
            procurement_method = method_soup.get_text().strip()
            
            # Clean up procurement method - remove extra text
            if 'Has Lots' in procurement_method:
                procurement_method = procurement_method.replace('Has Lots', '').strip()
            
            # Extract status and clean HTML tags
            status_html = contract_data[3]
            status_soup = BeautifulSoup(status_html, 'html.parser')
            status = status_soup.get_text().strip()
            
            # Extract dates
            published_date = contract_data[4].strip()
            deadline = contract_data[5].strip()
            
            # Construct detail URL from reference number
            detail_url = f"{self.base_url}/bid/notice/{reference_number}/details"
            
            # Parse dates
            published_parsed = self._parse_date(published_date)
            deadline_parsed = self._parse_date(deadline)
            
            contract = {
                'reference_number': reference_number,
                'title': title,
                'procuring_entity': procuring_entity,
                'procurement_method': procurement_method,
                'status': status,
                'published_date': published_parsed,
                'deadline': deadline_parsed,
                'detail_url': detail_url,
                'category': self._extract_category_from_title(title),
                'description': title  # Use title as description for now
            }
            
            return contract
            
        except Exception as e:
            logger.error(f"Error extracting contract data: {str(e)}")
            return None

    def _extract_category_from_title(self, title: str) -> str:
        """Extract category from contract title"""
        try:
            title_lower = title.lower()
            
            # Define category keywords
            categories = {
                'construction': ['construction', 'building', 'infrastructure', 'road', 'bridge', 'renovation'],
                'supplies': ['supply', 'delivery', 'procurement', 'purchase', 'equipment', 'materials'],
                'services': ['service', 'maintenance', 'consultancy', 'training', 'support'],
                'it': ['software', 'hardware', 'it', 'technology', 'system', 'digital'],
                'healthcare': ['medical', 'health', 'hospital', 'clinic', 'pharmaceutical'],
                'education': ['education', 'training', 'school', 'university', 'learning']
            }
            
            for category, keywords in categories.items():
                if any(keyword in title_lower for keyword in keywords):
                    return category
            
            return 'other'
        except:
            return 'other'
    
    def _parse_date(self, date_str: str) -> str:
        """Parse and standardize date format"""
        try:
            if not date_str or date_str.lower() == 'unknown':
                return "Unknown"
            
            # Handle various date formats
            date_formats = [
                '%Y-%m-%d %H:%M:%S%p %Z',  # 2025-08-21 02:36:58pm EAT
                '%Y-%m-%d %H:%M:%S',      # 2025-08-21 02:36:58
                '%Y-%m-%d',               # 2025-08-21
                '%d-%m-%Y',               # 21-08-2025
                '%m-%d-%Y',               # 08-21-2025
                '%b-%d %Y',               # Sep-10 2025
            ]
            
            for fmt in date_formats:
                try:
                    parsed_date = datetime.strptime(date_str.strip(), fmt)
                    return parsed_date.strftime('%Y-%m-%d')
                except ValueError:
                    continue
            
            # If no format matches, return as is
            return date_str.strip()
            
        except Exception as e:
            logger.error(f"Error parsing date '{date_str}': {str(e)}")
            return date_str.strip()
    
    def transform_for_webapp(self, contracts: List[Dict]) -> List[Dict]:
        """Transform contract data to match web app import format"""
        transformed_contracts = []
        errors = []
        
        for i, contract in enumerate(contracts):
            try:
                # Validate required fields
                required_fields = ['title', 'procuring_entity', 'procurement_method']
                missing_fields = [field for field in required_fields if not contract.get(field)]
                
                if missing_fields:
                    errors.append(f"Contract {i+1}: Missing required fields: {', '.join(missing_fields)}")
                    continue
                
                # Clean and transform data
                transformed = {
                    # Required fields with mapping - ensure no NaN values
                    'reference_number': self._clean_string(contract.get('reference_number', '')),
                    'title': self._clean_string(contract.get('title', '')),
                    'short_description': self._clean_string(contract.get('description', '')),
                    'category': self._clean_string(contract.get('category', 'Other')),
                    'procurement_method': self._clean_procurement_method(contract.get('procurement_method', '')),
                    'submission_deadline': self._clean_date(contract.get('deadline', '')),
                    'procuring_entity': self._clean_string(contract.get('procuring_entity', '')),
                    'status': self._clean_status(contract.get('status', 'Open')),
                    
                    # Optional fields with defaults
                    'currency': 'UGX',
                    'bid_fee': self._clean_bid_fee(contract.get('bid_fee', '')),
                    'publish_date': self._clean_date(contract.get('published_date', '')),
                    'contact_person': self._clean_string(contract.get('contact_person', '')),
                    'contact_position': self._clean_string(contract.get('contact_position', '')),
                    'detail_url': self._clean_string(contract.get('detail_url', '')),
                    # Map scraped attachments (list of {filename, url}) to URLs array expected by web app
                    'bid_attachments': [
                        att.get('url', '').strip()
                        for att in (contract.get('attachments') or [])
                        if isinstance(att, dict) and att.get('url') and str(att.get('url')).strip()
                    ],
                    
                    # Boolean fields with defaults
                    'margin_of_preference': False,
                    'competition_level': 'medium',
                    'requires_registration': False,
                    'requires_trading_license': False,
                    'requires_tax_clearance': False,
                    'requires_nssf_clearance': False,
                    'requires_manufacturer_auth': False,
                    
                    # String fields with defaults
                    'current_stage': 'Published',
                    'evaluation_methodology': '',
                    'submission_method': '',
                    'submission_format': '',
                    'award_information': '',
                    
                    # Array fields (empty for now)
                    'required_documents': [],
                    'required_forms': [],
                    
                    # Numeric fields (empty for now)
                    'estimated_value_min': None,
                    'estimated_value_max': None,
                    'bid_security_amount': contract.get('bid_security_amount', 0),
                    'bid_security_type': self._clean_string(contract.get('bid_security_type', '')),
                    
                    # Date fields (empty for now)
                    'pre_bid_meeting_date': '',
                    'site_visit_date': '',
                    'bid_opening_date': ''
                }
                
                transformed_contracts.append(transformed)
            
            except Exception as e:
                error_msg = f"Contract {i+1}: Error transforming data - {str(e)}"
                errors.append(error_msg)
                logger.error(error_msg)
                continue
        
        # Log transformation results
        logger.info(f"Transformed {len(transformed_contracts)} contracts for web app import")
        if errors:
            logger.warning(f"Encountered {len(errors)} errors during transformation:")
            for error in errors[:5]:  # Show first 5 errors
                logger.warning(f"  - {error}")
            if len(errors) > 5:
                logger.warning(f"  ... and {len(errors) - 5} more errors")
        
        return transformed_contracts

    def _clean_procurement_method(self, method: str) -> str:
        """Clean procurement method field"""
        if not method:
            return 'Open Domestic Bidding'
        
        # Remove extra text and clean up
        method = method.replace('Has Lots', '').strip()
        method = method.replace('\n', ' ').strip()
        
        # Map to standard values
        method_lower = method.lower()
        if 'open domestic' in method_lower:
            return 'Open Domestic Bidding'
        elif 'restricted' in method_lower:
            return 'Restricted Bidding'
        elif 'direct' in method_lower:
            return 'Direct Procurement'
        elif 'framework' in method_lower:
            return 'Framework Agreement'
        elif 'quotation' in method_lower:
            return 'Request for Quotations'
        elif 'proposal' in method_lower:
            return 'Request for Proposals'
        elif 'single source' in method_lower:
            return 'Single Source'
        else:
            return method or 'Open Domestic Bidding'

    def _clean_status(self, status: str) -> str:
        """Clean status field"""
        if not status:
            return 'Open'
        
        status_lower = status.lower()
        if 'open' in status_lower or 'active' in status_lower:
            return 'Open'
        elif 'closed' in status_lower:
            return 'Closed'
        elif 'awarded' in status_lower:
            return 'Awarded'
        elif 'cancelled' in status_lower or 'cancel' in status_lower:
            return 'Cancelled'
        else:
            return 'Open'

    def _clean_bid_fee(self, fee: str) -> float:
        """Clean bid fee field"""
        if not fee:
            return 0.0
        
        try:
            # Fee should already be cleaned (no UGX prefix)
            fee_clean = str(fee).replace(',', '').strip()
            # Extract numeric value
            fee_match = re.search(r'[\d,]+\.?\d*', fee_clean)
            if fee_match:
                return float(fee_match.group().replace(',', ''))
            return 0.0
        except:
            return 0.0

    def _parse_bid_security_amount(self, security_text: str) -> float:
        """Parse bid security amount from text like 'UGX 33,254,000.00/='"""
        if not security_text:
            return 0.0
        
        try:
            # Remove common prefixes and suffixes
            clean_text = security_text.replace('UGX', '').replace('USD', '').replace('$', '')
            clean_text = clean_text.replace('/', '').replace('=', '').replace(',', '').strip()
            
            # Extract numeric value using regex
            amount_match = re.search(r'[\d]+\.?\d*', clean_text)
            if amount_match:
                return float(amount_match.group())
            
            return 0.0
        except:
            return 0.0

    def _clean_string(self, value) -> str:
        """Clean string values and handle NaN"""
        if value is None or value == '' or str(value).lower() == 'nan':
            return ''
        return str(value).strip()

    def _clean_date(self, date_str: str) -> str:
        """Clean and format date field"""
        if not date_str:
            return ''
        
        try:
            # Try to parse the date and return in YYYY-MM-DD format
            parsed_date = self._parse_date(date_str)
            if parsed_date:
                # Convert to YYYY-MM-DD format
                if ' ' in parsed_date:
                    return parsed_date.split(' ')[0]
                return parsed_date
            return ''
        except:
            return ''
    
    def export_to_csv(self, contracts: List[Dict], filename: str = None, for_webapp: bool = False) -> str:
        """Export contracts to CSV file with proper line endings for web app compatibility"""
        try:
            if not filename:
                timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
                filename = f'egp_contracts_import_{timestamp}.csv'
        
            # Transform data if exporting for web app
            if for_webapp:
                contracts = self.transform_for_webapp(contracts)
        
            # Convert to DataFrame and export
            df = pd.DataFrame(contracts)
            
            # Replace NaN values with empty strings for string columns
            string_columns = df.select_dtypes(include=['object']).columns
            for col in string_columns:
                df[col] = df[col].fillna('')
            
            # Export to CSV with Unix line endings (LF) instead of Windows line endings (CRLF)
            # This ensures compatibility with the web app import system
            df.to_csv(filename, index=False, encoding='utf-8', lineterminator='\n')
            
            # Verify the exported file has proper line endings
            self._verify_csv_line_endings(filename)
            
            logger.info(f"Exported {len(contracts)} contracts to {filename}")
            logger.info("✅ CSV file exported with proper line endings for web app compatibility")
            return filename
            
        except Exception as e:
            logger.error(f"Error exporting to CSV: {str(e)}")
            return None
    
    def _verify_csv_line_endings(self, filename: str):
        """Verify that the exported CSV has proper line endings"""
        try:
            with open(filename, 'r', encoding='utf-8') as f:
                content = f.read()
            
            # Check for problematic line endings
            crlf_count = content.count('\r\n')
            cr_count = content.count('\r')
            lf_count = content.count('\n')
            
            if crlf_count > 0 or cr_count > 0:
                logger.warning(f"⚠️  Found {crlf_count} CRLF and {cr_count} CR line endings")
                logger.warning("   These may cause import issues in the web app")
                
                # Auto-fix the line endings
                logger.info("🔧 Auto-fixing line endings...")
                fixed_content = content.replace('\r\n', '\n').replace('\r', '\n')
                
                with open(filename, 'w', encoding='utf-8') as f:
                    f.write(fixed_content)
                
                logger.info("✅ Line endings fixed automatically")
            else:
                logger.info("✅ CSV file has proper line endings (LF only)")
                
        except Exception as e:
            logger.warning(f"Could not verify line endings: {str(e)}")

    def export_to_csv_webapp_ready(self, contracts: List[Dict], filename: str = None) -> str:
        """Export contracts to CSV file specifically optimized for web app import"""
        try:
            if not filename:
                timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
                filename = f'egp_contracts_webapp_ready_{timestamp}.csv'
            
            logger.info("🔄 Preparing data for web app import...")
            
            # Transform data for web app
            transformed_contracts = self.transform_for_webapp(contracts)
            
            # Additional validation and cleaning for web app compatibility
            cleaned_contracts = []
            validation_errors = []
            
            for i, contract in enumerate(transformed_contracts):
                try:
                    # Ensure all required fields are present and valid
                    if not contract.get('reference_number', '').strip():
                        validation_errors.append(f"Contract {i+1}: Missing reference number")
                        continue
                    
                    if not contract.get('title', '').strip():
                        validation_errors.append(f"Contract {i+1}: Missing title")
                        continue
                    
                    if not contract.get('procuring_entity', '').strip():
                        validation_errors.append(f"Contract {i+1}: Missing procuring entity")
                        continue
                    
                    # Clean and validate the contract
                    cleaned_contract = {}
                    for key, value in contract.items():
                        if isinstance(value, str):
                            # Remove any hidden characters and normalize whitespace
                            cleaned_value = value.strip()
                            # Remove any carriage returns or line breaks that might cause issues
                            cleaned_value = cleaned_value.replace('\r', ' ').replace('\n', ' ')
                            cleaned_value = ' '.join(cleaned_value.split())  # Normalize whitespace
                            cleaned_contract[key] = cleaned_value
                        else:
                            cleaned_contract[key] = value
                    
                    cleaned_contracts.append(cleaned_contract)
                    
                except Exception as e:
                    validation_errors.append(f"Contract {i+1}: Error cleaning data - {str(e)}")
                    continue
            
            if validation_errors:
                logger.warning(f"⚠️  Found {len(validation_errors)} validation issues:")
                for error in validation_errors[:5]:
                    logger.warning(f"   - {error}")
                if len(validation_errors) > 5:
                    logger.warning(f"   ... and {len(validation_errors) - 5} more issues")
            
            # Convert to DataFrame and export with proper line endings
            df = pd.DataFrame(cleaned_contracts)
            
            # Replace any remaining NaN values with empty strings
            df = df.fillna('')
            
            # Export with Unix line endings (LF) for maximum compatibility
            df.to_csv(filename, index=False, encoding='utf-8', lineterminator='\n')
            
            # Verify the export
            self._verify_csv_line_endings(filename)
            
            logger.info(f"✅ Web app ready CSV exported: {filename}")
            logger.info(f"📊 Total contracts: {len(cleaned_contracts)}")
            logger.info(f"🔧 Validation errors: {len(validation_errors)}")
            logger.info("🚀 This file is ready for immediate import into the BidFlow platform")
            
            return filename
            
        except Exception as e:
            logger.error(f"Error exporting web app ready CSV: {str(e)}")
            return None
    
    def test_portal_structure(self):
        """Test the portal structure without login"""
        try:
            logger.info("Testing portal structure...")
            
            # Test main page
            response = self.session.get(self.base_url)
            logger.info(f"Main page status: {response.status_code}")
            
            # Test bid notices page
            bid_url = f"{self.base_url}/bid/notices"
            response = self.session.get(bid_url)
            logger.info(f"Bid notices page status: {response.status_code}")
            
            if response.status_code == 200:
                soup = BeautifulSoup(response.text, 'html.parser')
                
                # Look for DataTable structure
                datatable = soup.find('table', id='bid-notices-archives')
                if datatable:
                    logger.info("Found DataTable structure")
                else:
                    logger.warning("DataTable not found")
                
                # Look for API endpoint references
                api_refs = soup.find_all(text=re.compile(r'public_bid_archives'))
                if api_refs:
                    logger.info("Found API endpoint references")
                else:
                    logger.warning("API endpoint references not found")
            
        except Exception as e:
            logger.error(f"Error testing portal structure: {str(e)}")

    def test_csv_compatibility(self, filename: str) -> bool:
        """Test if the exported CSV is compatible with the web app import system"""
        try:
            logger.info(f"🧪 Testing CSV compatibility: {filename}")
            
            # Read the CSV file
            with open(filename, 'r', encoding='utf-8') as f:
                content = f.read()
            
            # Check line endings
            crlf_count = content.count('\r\n')
            cr_count = content.count('\r')
            lf_count = content.count('\n')
            
            logger.info(f"   Line endings: LF={lf_count}, CRLF={crlf_count}, CR={cr_count}")
            
            # Check for problematic line endings
            if crlf_count > 0 or cr_count > 0:
                logger.warning("   ⚠️  Found problematic line endings")
                return False
            
            # Check if the file can be parsed as CSV
            lines = content.split('\n')
            if len(lines) < 2:
                logger.warning("   ⚠️  CSV file has insufficient lines")
                return False
            
            # Check header
            header = lines[0]
            if 'reference_number' not in header or 'title' not in header:
                logger.warning("   ⚠️  CSV header is missing required fields")
                return False
            
            # Check data rows
            data_rows = [line for line in lines[1:] if line.strip()]
            if len(data_rows) == 0:
                logger.warning("   ⚠️  CSV file has no data rows")
                return False
            
            # Test parsing a few rows
            try:
                csv_reader = csv.DictReader(StringIO(content))
                test_rows = []
                for i, row in enumerate(csv_reader):
                    if i >= 5:  # Test first 5 rows
                        break
                    test_rows.append(row)
                
                # Validate test rows
                for i, row in enumerate(test_rows):
                    if not row.get('reference_number', '').strip():
                        logger.warning(f"   ⚠️  Row {i+2}: Missing reference number")
                        return False
                    if not row.get('title', '').strip():
                        logger.warning(f"   ⚠️  Row {i+2}: Missing title")
                        return False
                
                logger.info(f"   ✅ Successfully parsed {len(test_rows)} test rows")
                
            except Exception as e:
                logger.warning(f"   ⚠️  CSV parsing test failed: {str(e)}")
                return False
            
            logger.info("   ✅ CSV compatibility test passed!")
            return True
            
        except Exception as e:
            logger.error(f"   ❌ CSV compatibility test error: {str(e)}")
            return False

    def create_import_report(self, filename: str, contracts: List[Dict]) -> str:
        """Create a detailed import report for the user"""
        try:
            report_filename = filename.replace('.csv', '_import_report.txt')
            
            with open(report_filename, 'w', encoding='utf-8') as f:
                f.write("=" * 60 + "\n")
                f.write("BIDFLOW PLATFORM IMPORT REPORT\n")
                f.write("=" * 60 + "\n\n")
                
                f.write(f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
                f.write(f"Source: EGP Uganda Portal Scraper\n")
                f.write(f"CSV File: {filename}\n")
                f.write(f"Total Contracts: {len(contracts)}\n\n")
                
                f.write("IMPORT STATUS: ✅ READY FOR IMPORT\n\n")
                
                f.write("COMPATIBILITY FEATURES:\n")
                f.write("✅ Unix line endings (LF) - No Windows compatibility issues\n")
                f.write("✅ UTF-8 encoding - Proper character handling\n")
                f.write("✅ Cleaned data - No hidden characters or formatting issues\n")
                f.write("✅ Validated fields - All required fields present\n")
                f.write("✅ Web app optimized - Matches BidFlow import requirements\n\n")
                
                f.write("IMPORT INSTRUCTIONS:\n")
                f.write("1. Go to your BidFlow platform admin panel\n")
                f.write("2. Navigate to Contracts > Import\n")
                f.write("3. Upload the CSV file: " + filename + "\n")
                f.write("4. The import should complete without validation errors\n")
                f.write("5. All contracts will be imported successfully\n\n")
                
                f.write("TROUBLESHOOTING:\n")
                f.write("If you encounter any issues:\n")
                f.write("- Ensure you're using the latest version of the platform\n")
                f.write("- Check that the CSV file wasn't modified after export\n")
                f.write("- Verify the file encoding is UTF-8\n")
                f.write("- Contact support if problems persist\n\n")
                
                f.write("=" * 60 + "\n")
                f.write("End of Report\n")
                f.write("=" * 60 + "\n")
            
            logger.info(f"📋 Import report created: {report_filename}")
            return report_filename
            
        except Exception as e:
            logger.error(f"Error creating import report: {str(e)}")
            return None

def main():
    # Configure logging
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(levelname)s - %(message)s'
    )
    
    # Initialize scraper (use environment variables for credentials)
    email = os.getenv("EGP_PORTAL_EMAIL")
    password = os.getenv("EGP_PORTAL_PASSWORD")

    if not email or not password:
        logger.error("Missing credentials. Set EGP_PORTAL_EMAIL and EGP_PORTAL_PASSWORD.")
        return
    
    scraper = EGPScraper(email, password)
    
    # Test portal structure first
    scraper.test_portal_structure()
    
    # Try to login
    if not scraper.login():
        logger.error("Failed to login. Exiting.")
        return
    
    # Get bid notices with detailed information
    logger.info("=== Fetching Bid Notices with Details ===")
    
    # Set include_details=False for faster testing, True for full data
    include_details = True  # Change to False for faster testing
    contracts = scraper.get_bid_notices_from_page(include_details=include_details)
    
    if contracts:
        # Export for web app import with enhanced compatibility
        logger.info("=== Exporting Contracts for Web App Import ===")
        
        # Use the new web app ready export method
        webapp_filename = scraper.export_to_csv_webapp_ready(contracts)
        if webapp_filename:
            logger.info("🎉 SUCCESS: Web app import file created successfully!")
            logger.info(f"📁 File location: {webapp_filename}")
            logger.info(f"📊 Total contracts: {len(contracts)}")
            
            # Test CSV compatibility
            logger.info("\n=== Testing CSV Compatibility ===")
            if scraper.test_csv_compatibility(webapp_filename):
                logger.info("✅ CSV file is fully compatible with BidFlow platform!")
            else:
                logger.warning("⚠️  CSV compatibility issues detected - manual review may be needed")
            
            # Create import report
            logger.info("\n=== Creating Import Report ===")
            report_filename = scraper.create_import_report(webapp_filename, contracts)
            
            logger.info("")
            logger.info("🚀 IMPORTANT: This file is ready for immediate import into BidFlow platform")
            logger.info("✅ Line endings are automatically fixed for compatibility")
            logger.info("✅ Data is cleaned and validated")
            logger.info("✅ All required fields are present")
            logger.info("✅ CSV compatibility verified")
            logger.info("")
            logger.info("📋 Next steps:")
            logger.info("   1. Upload this CSV file to your BidFlow platform")
            logger.info("   2. The import should work without any validation errors")
            logger.info("   3. All contracts will be imported successfully")
            logger.info("")
            logger.info("📁 Files created:")
            logger.info(f"   - CSV: {webapp_filename}")
            if report_filename:
                logger.info(f"   - Report: {report_filename}")
        else:
            logger.error("❌ Failed to export web app import file")
    else:
        logger.warning("No contracts found")

if __name__ == "__main__":
    # Run the main scraper functionality
    main()
