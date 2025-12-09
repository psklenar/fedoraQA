#!/usr/bin/python3
# Requires testing-farm package


"""This file contains a non-interactive function to report release
validation results. It reuses logic from report_results.py but accepts
all parameters as function arguments instead of prompting the user.
"""

import argparse
import logging
import re
import sys
import time
import requests
import xml.etree.ElementTree as ET
import wikitcms.wiki
import wikitcms.result
from relval.report_results import comment_string


def get_wiki_connection(wiki=None, release=None, compose=None, milestone=None, sections=None, environment=None, testtype=None, production=False, dist="Fedora"):
    """
    Common function to connect to wiki and get validation event and test type page.
    
    Args:
        wiki: Existing wiki connection (if None, creates new connection)
        release: Release number (if None, gets from current compose)
        compose: Compose name (if None, gets from current compose)
        milestone: Milestone (if None, gets from current compose)
        sections: List of sections (optional, for filtering)
        environment: Environment name (optional, for reference)
        testtype: Test type name (required if getting page)
        production: Use production wiki (default: False, uses staging)
        dist: Distribution name (default: "Fedora")
    
    Returns:
        tuple: (wiki, event, release, milestone, compose, page)
        If testtype is None, page will be None
    """
    import wikitcms.wiki
    
    # Connect to wiki if not provided
    if wiki is None:
        if production:
            wiki = wikitcms.wiki.Wiki("fedoraproject.org")
        else:
            wiki = wikitcms.wiki.Wiki("stg.fedoraproject.org")
        wiki.login()
    
    # Get current compose information if not provided
    if release is None or milestone is None or compose is None:
        curr = wiki.get_current_compose(dist=dist)
        if release is None:
            release = int(curr["release"])
        if milestone is None:
            milestone = curr["milestone"]
        if compose is None:
            compose = max(curr["compose"], curr["date"])
    
    # Get the validation event
    event = wiki.get_validation_event(
        release=release, milestone=milestone, compose=compose, dist=dist
    )
    
    # Get test type page if testtype is provided
    page = None
    if testtype:
        pages = [pag for pag in event.result_pages if pag.testtype == testtype]
        if not pages:
            raise IndexError(f"Test type '{testtype}' not found in validation event")
        page = pages[0]
    
    return wiki, event, release, milestone, compose, page


def get_testcases(wiki=None, release=None, compose=None, milestone=None, sections=None, environment=None, testtype="Cloud", production=False):
    """
    Get list of test cases from wiki for a specific test type.
    
    Args:
        wiki: Wiki connection object (optional, will create if None)
        release: Release number (optional, gets from current compose if None)
        compose: Compose name (optional, gets from current compose if None)
        milestone: Milestone (optional, gets from current compose if None)
        sections: List of section names to filter (optional)
        environment: Environment name (optional, for reference)
        testtype: Test type name (default: "Cloud")
        production: Use production wiki (default: False)
    
    Returns:
        list: List of test case names
    """
    # Get wiki connection and test type page using common function
    wiki, event, release, milestone, compose, page = get_wiki_connection(
        wiki=wiki, release=release, compose=compose, milestone=milestone,
        sections=sections, environment=environment, testtype=testtype,
        production=production
    )
    
    # Print header (only in debug mode)
    logging.debug(f"\n{'='*60}")
    logging.debug(f"Test Cases from Wiki - {testtype} Test Type (Release: {release}, Compose: {compose}, Milestone: {milestone})")
    logging.debug(f"{'='*60}\n")
    logging.debug(f"Test Type: {page.testtype}")
    logging.debug(f"{'-'*60}")
    
    # Get all result rows (test cases)
    tests = page.get_resultrows(statuses=["pass", "warn", "fail", "inprogress"])
    
    # Group by section
    page_sections = page.results_sections
    testsecs = {t.secid for t in tests}
    page_sections = [s for s in page_sections if s["index"] in testsecs]
    
    all_testcases = []
    for section in page_sections:
        section_tests = [t for t in tests if t.secid == section["index"]]
        if section_tests:
            import re
            tag_patt = re.compile("<.*?>")
            sec_line_clean = tag_patt.sub("", section["line"])
            
            # Filter by sections if provided
            if sections is None or any(sec_filter in sec_line_clean or sec_line_clean in sec_filter for sec_filter in sections):
                logging.debug(f"\n  Section: {sec_line_clean}")
                for test in section_tests:
                    testcase_name = test.testcase
                    logging.debug(f"    - {testcase_name}")
                    all_testcases.append(testcase_name)
    logging.debug("")
    
    return all_testcases


def fetch_and_cache_xunit_xml(api_url, max_retries=3, retry_interval=10, cache=None):
    """
    Fetch Testing Farm API data and download/cache the xunit XML results.
    
    Args:
        api_url: The Testing Farm API URL (e.g., https://api.dev.testing-farm.io/v0.1/requests/<uuid>)
        max_retries: Maximum number of retry attempts (default: 3)
        retry_interval: Seconds to wait between retries (default: 10)
        cache: Optional dict to cache results (keyed by api_url)
    
    Returns:
        dict: Dictionary containing:
            - overall: Overall result as string (e.g., "pass", "fail", "warn")
            - xunit_url: XUnit URL as string (junit XML link from result.xunit_url)
            - xunit_xml_root: Parsed XML root element (or None if not available)
            - test_plan_names: List of all test plan names from XML
    """
    # Check cache first
    if cache is not None and api_url in cache:
        logging.debug(f'Using cached XML data for {api_url}')
        return cache[api_url]
    
    try:
        # Fetch API data with retry logic
        for attempt in range(1, max_retries + 1):
            try:
                response = requests.get(api_url)
                response.raise_for_status()
                data = response.json()
                break
            except requests.exceptions.RequestException as e:
                if attempt < max_retries:
                    logging.warning(f'API request failed (attempt {attempt}/{max_retries}): {e}, retrying in {retry_interval} seconds')
                    time.sleep(retry_interval)
                else:
                    logging.error(f'API request failed after {max_retries} attempts: {e}')
                    raise
        
        # Extract overall result and xunit_url from API response
        # xunit_url is located at: result.xunit_url
        result_data = data.get('result', {})
        overall = result_data.get('overall', 'warn')
        xunit_url = result_data.get('xunit_url', '')  # This is the junit XML link
        
        # Normalize overall result
        if overall == 'passed':
            overall = 'pass'
        elif overall == 'failed':
            overall = 'fail'
        
        xunit_xml_root = None
        test_plan_names = []
        
        # If xunit_url is available, fetch and parse it
        if xunit_url:
            try:
                # Fetch xunit XML with retry logic
                for attempt in range(1, max_retries + 1):
                    try:
                        xunit_response = requests.get(xunit_url)
                        xunit_response.raise_for_status()
                        xunit_content = xunit_response.text
                        break
                    except requests.exceptions.RequestException as e:
                        if attempt < max_retries:
                            logging.warning(f'XUnit URL request failed (attempt {attempt}/{max_retries}): {e}, retrying in {retry_interval} seconds')
                            time.sleep(retry_interval)
                        else:
                            logging.error(f'XUnit URL request failed after {max_retries} attempts: {e}')
                            raise
                
                # Parse XML content
                xunit_xml_root = ET.fromstring(xunit_content)
                
                # Extract all test plan names from XML
                for testsuite in xunit_xml_root.findall('.//testsuite'):
                    test_plan_name = testsuite.get('name', '')
                    if test_plan_name:
                        test_plan_names.append(test_plan_name)
                
            except ET.ParseError as e:
                logging.error(f'Error parsing XUnit XML from {xunit_url}: {e}')
            except requests.exceptions.RequestException as e:
                logging.error(f'Error fetching XUnit URL {xunit_url}: {e}')
            except Exception as e:
                logging.error(f'Unexpected error processing XUnit XML: {e}')
        
        result = {
            'overall': overall,
            'xunit_url': xunit_url,
            'xunit_xml_root': xunit_xml_root,
            'test_plan_names': test_plan_names
        }
        
        # Cache the result
        if cache is not None:
            cache[api_url] = result
        
        return result
        
    except requests.exceptions.RequestException as e:
        logging.error(f'Error fetching API data from {api_url}: {e}')
        result = {
            'overall': 'warn',
            'xunit_url': '',
            'xunit_xml_root': None,
            'test_plan_names': []
        }
        if cache is not None:
            cache[api_url] = result
        return result
    except Exception as e:
        logging.error(f'Unexpected error fetching and caching XUnit XML: {e}')
        result = {
            'overall': 'warn',
            'xunit_url': '',
            'xunit_xml_root': None,
            'test_plan_names': []
        }
        if cache is not None:
            cache[api_url] = result
        return result


def match_qatestcase_with_fmf_plan_name(xunit_data, qatestcase, fmf_plan_name):
    """
    Match a QA testcase with FMF plan name in cached XUnit XML data.
    This function can be called multiple times with different testcases/plan names
    without re-downloading the XML.
    
    Args:
        xunit_data: Dictionary from fetch_and_cache_xunit_xml() containing:
            - xunit_xml_root: Parsed XML root element
            - test_plan_names: List of all test plan names
        qatestcase: QA testcase string (e.g., "QA:Testcase_base_system_logging")
        fmf_plan_name: FMF plan name string (e.g., "cloud")
    
    Returns:
        dict: Dictionary containing:
            - qatestcase_found: bool indicating if QA testcase was found in xunit XML path
            - fmf_plan_name_found: bool indicating if FMF plan name was found in xunit XML path
            - matching_test_plans: list of test plan names that match both qatestcase and fmf_plan_name
    """
    qatestcase_found = False
    fmf_plan_name_found = False
    matching_test_plans = []
    
    # Extract testcase name from qatestcase (remove "QA:" prefix if present)
    # "QA:Testcase_base_system_logging" -> "Testcase_base_system_logging"
    testcase_name = qatestcase.replace("QA:", "").strip()
    if not testcase_name.startswith("Testcase_"):
        # If it doesn't start with Testcase_, add it
        testcase_name = f"Testcase_{testcase_name.replace('Testcase_', '')}"
    
    # Use cached test plan names or parse from XML root
    if xunit_data.get('test_plan_names'):
        test_plan_names = xunit_data['test_plan_names']
    elif xunit_data.get('xunit_xml_root') is not None:
        # Fallback: extract from XML root if test_plan_names not available
        test_plan_names = []
        for testsuite in xunit_data['xunit_xml_root'].findall('.//testsuite'):
            test_plan_name = testsuite.get('name', '')
            if test_plan_name:
                test_plan_names.append(test_plan_name)
    else:
        # No XML data available
        return {
            'qatestcase_found': False,
            'fmf_plan_name_found': False,
            'matching_test_plans': []
        }
    
    # Process each test plan name
    for test_plan_name in test_plan_names:
        # Test plan name format: /plans/{fmf_plan_name}/.../Testcase_xxx/Testcase_yyy/...
        # Example: /plans/cloud/external/Testcase_base_service_manipulation
        # Example: /plans/cloud/local/wiki/Testcase_base_startup/Testcase_base_reboot_unmount/Testcase_base_system_logging/...
        if test_plan_name.startswith('/plans/'):
            # Split path into elements
            path_elements = [elem for elem in test_plan_name.split('/') if elem]
            
            # Check if FMF plan name appears anywhere in the path elements
            plan_name_in_path = False
            for element in path_elements:
                if fmf_plan_name.lower() == element.lower():
                    plan_name_in_path = True
                    fmf_plan_name_found = True
                    break
            
            # Check if testcase appears anywhere in the path elements
            # The testcase can be any element in the path
            testcase_in_path = False
            for element in path_elements:
                if element == testcase_name:
                    testcase_in_path = True
                    qatestcase_found = True
                    break
            
            # If both match, add to matching list
            if plan_name_in_path and testcase_in_path:
                matching_test_plans.append(test_plan_name)
    
    return {
        'qatestcase_found': qatestcase_found,
        'fmf_plan_name_found': fmf_plan_name_found,
        'matching_test_plans': matching_test_plans
    }


def main():
    """main function to report validation results non-interactively."""
    parser = argparse.ArgumentParser(description="Report release validation results non-interactively.")
    parser.add_argument("--sections", nargs="+", default=["x86_64"],
                        help="List of sections to report results for (default: x86_64), e.g. x86_64 aarch64")
    parser.add_argument("--production", action="store_true",
                        help="Use production wiki instead of staging (default: staging)")
    parser.add_argument("--debug", action="store_true",
                        help="Enable debug logging to show detailed information")
    parser.add_argument("--try", dest="try_mode", action="store_true",
                        help="Only check if results exist, don't add them. Prints 'RESULTS MISSING'")
    parser.add_argument("--comment", default="",
                        help="Comment to add to test results")
    parser.add_argument("--status", default="warn", choices=["pass", "fail", "warn"],
                        help="Status for test results: pass, fail, or warn (default: 'warn')")
    
    args = parser.parse_args()
    
    # Set up logging based on --debug flag
    if args.debug:
        logging.basicConfig(level=logging.DEBUG, format='%(levelname)s: %(message)s')
    else:
        logging.basicConfig(level=logging.WARNING, format='%(levelname)s: %(message)s')
    
    # Set up wiki connection
    # Use staging by default, production if --production is specified
    test = not args.production
    if test:
        wiki = wikitcms.wiki.Wiki("stg.fedoraproject.org")
    else:
        wiki = wikitcms.wiki.Wiki("fedoraproject.org")
    wiki.login()
    curr = wiki.get_current_compose(dist='Fedora')
    release = int(curr["release"])
    milestone = curr["milestone"]
    compose = max(curr["compose"], curr["date"])
    sections = args.sections
    environment="EC2 (KVM)"
    testtype="Cloud"
    #TODO: from options when needed^^^

# use_comment=True means the testcase will get the comment, False means comment=None
#    testcase_list = [
#        ("QA:Testcase_base_startup", True),
#        ("QA:Testcase_base_reboot_unmount", False),
#        ("QA:Testcase_base_system_logging", False),
#        ("QA:Testcase_base_update_cli", False),
#        ("QA:Testcase_package_install_remove", False),
#        ("QA:Testcase_base_artwork_release_identification", False),
#        ("QA:Testcase_base_edition_self_identification", False),
#        ("QA:Testcase_base_services_start", False),
#        ("QA:Testcase_base_selinux", False),
#        ("QA:Testcase_base_service_manipulation", False),
#   ]

    # List of sections to report results for (from command line)
    testcases = get_testcases(wiki=wiki, release=release, compose=compose, milestone=milestone, sections=sections, environment=environment, testtype=testtype, production=args.production)
    
    # Example usage: Fetch and cache XUnit XML, then match each testcase
    example_api_url = "https://api.dev.testing-farm.io/v0.1/requests/0e1ecc90-0ccc-468d-9630-f61d8936ac34"
    xunit_cache = {}
    xunit_data = fetch_and_cache_xunit_xml(example_api_url, cache=xunit_cache)
    logging.debug(f"Overall: {xunit_data['overall']}, XUnit URL: {xunit_data['xunit_url']}")
    
    # Match each testcase from the testcases list
    for qatestcase in testcases:
        match_result = match_qatestcase_with_fmf_plan_name(xunit_data, qatestcase, "cloud")
        if match_result['qatestcase_found']:
            print(f"Found: {qatestcase} - Result: {xunit_data['overall']} ({len(match_result['matching_test_plans'])} plans)")
            logging.debug(f"  Plans: {match_result['matching_test_plans']}")
        else:
            logging.debug(f"Not found: {qatestcase}")
    
    #sys.exit(0)
    # Report results for all QA:testcases in the list for each section
    status=args.status
    comment=args.comment
    if comment:
        comment = comment_string(comment, maxlen=250)
    else:
        comment = None
    allow_duplicate=True
    try_mode=args.try_mode




if __name__ == "__main__":
    main()

