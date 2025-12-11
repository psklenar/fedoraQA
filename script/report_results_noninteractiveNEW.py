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
# Don't import comment_string from relval - use our own version that handles None
import relval


def comment_string(string, maxlen=250):
    """
    Take 'string' and wrap it in <ref> </ref> if it's not the empty
    string. Raise a ValueError if it's longer than maxlen.
    Handle None case like report_results_noninteractive.py
    """
    # Handle None case
    if string is None:
        return None
    string = string.strip()
    if maxlen and len(string) > maxlen:
        err = f"Comment is too long: {len(string)} characters, max is {maxlen}."
        raise ValueError(err)
    # Don't produce an empty <ref></ref> if there's no comment
    if not string:
        return string
    return f"<ref>{string}</ref>"


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
            # Handle None case for section["line"] - same pattern as modify_testcase_result
            sec_line = section.get("line") or ""
            sec_line_clean = tag_patt.sub("", sec_line)
            
            # Filter by sections if provided - ensure sec_filter is not None
            # Convert sections to list if it's a single string
            sections_list = [sections] if isinstance(sections, str) else sections if sections else []
            if sections is None or any(
                sec_filter and (str(sec_filter) in sec_line_clean or sec_line_clean in str(sec_filter))
                for sec_filter in sections_list if sec_filter is not None
            ):
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
        # artifacts_url is located at: run.artifacts
        result_data = data.get('result', {})
        overall = result_data.get('overall', 'warn')
        xunit_url = result_data.get('xunit_url', '')  # This is the junit XML link
        
        # Extract artifacts URL from run.artifacts
        run_data = data.get('run', {})
        artifacts_url = run_data.get('artifacts', '')
        
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
            'artifacts_url': artifacts_url,
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
            'artifacts_url': '',
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
            'artifacts_url': '',
            'xunit_xml_root': None,
            'test_plan_names': []
        }
        if cache is not None:
            cache[api_url] = result
        return result


def match_qatestcase_with_fmf_plan_name(xunit_data, qatestcase, fmf_plan_name_tag):
    """
    Match a QA testcase with FMF plan name tag in cached XUnit XML data.
    Extracts test results from matching testsuite elements.
    
    Args:
        xunit_data: Dictionary from fetch_and_cache_xunit_xml() containing:
            - xunit_xml_root: Parsed XML root element
            - test_plan_names: List of all test plan names
        qatestcase: QA testcase string (e.g., "QA:Testcase_base_system_logging")
        fmf_plan_name_tag: FMF plan name tag string (e.g., "cloud")
    
    Returns:
        dict: Dictionary containing:
            - qatestcase_found: bool indicating if QA testcase was found in xunit XML path
            - fmf_plan_name_found: bool indicating if FMF plan name tag was found in xunit XML path
            - matching_test_plans: list of tuples (test_plan_name, result) that match both qatestcase and fmf_plan_name_tag
            - testcase_result: The result from matching testsuite (e.g., "passed", "failed") or None
    """
    qatestcase_found = False
    fmf_plan_name_found = False
    matching_test_plans = []
    testcase_result = None
    
    # Extract testcase name from qatestcase (remove "QA:" prefix if present)
    # "QA:Testcase_base_system_logging" -> "Testcase_base_system_logging"
    testcase_name = qatestcase.replace("QA:", "").strip()
    if not testcase_name.startswith("Testcase_"):
        # If it doesn't start with Testcase_, add it
        testcase_name = f"Testcase_{testcase_name.replace('Testcase_', '')}"
    
    # Need to parse from XML root to get both name and result attributes
    if xunit_data.get('xunit_xml_root') is not None:
        root = xunit_data['xunit_xml_root']
    else:
        # No XML data available
        return {
            'qatestcase_found': False,
            'fmf_plan_name_found': False,
            'matching_test_plans': [],
            'testcase_result': None
        }
    
    # Process each testsuite element to get both name and result
    for testsuite in root.findall('.//testsuite'):
        test_plan_name = testsuite.get('name', '')
        test_plan_result = testsuite.get('result', '')  # Extract result attribute
        
        # Test plan name format: /plans/{fmf_plan_name_tag}/.../Testcase_xxx/Testcase_yyy/...
        # Example: /plans/cloud/external/Testcase_base_service_manipulation
        # Example: /plans/cloud/local/wiki/Testcase_base_startup/Testcase_base_reboot_unmount/Testcase_base_system_logging/...
        if test_plan_name.startswith('/plans/'):
            # Split path into elements
            path_elements = [elem for elem in test_plan_name.split('/') if elem]
            
            # Check if FMF plan name tag appears anywhere in the path elements
            plan_name_in_path = False
            for element in path_elements:
                if fmf_plan_name_tag.lower() == element.lower():
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
            
            # If both match, add to matching list with result
            if plan_name_in_path and testcase_in_path:
                matching_test_plans.append((test_plan_name, test_plan_result))
                # Use the first matching result (or could aggregate multiple results)
                if testcase_result is None:
                    testcase_result = test_plan_result
    
    return {
        'qatestcase_found': qatestcase_found,
        'fmf_plan_name_found': fmf_plan_name_found,
        'matching_test_plans': matching_test_plans,
        'testcase_result': testcase_result
    }


def modify_testcase_result(
    qatestcase,
    wiki=None,
    release=None,
    compose=None,
    milestone=None,
    sections=None,
    environment=None,
    testtype="Cloud",
    production=False,
    status=None,
    comment=None,
    bugs=None,
    allow_duplicate=False,
    artifacts_url=None
):
    """
    Add results for a single QA testcase in the wiki.
    Simplified version reusing patterns from report_results.py and get_testcases.
    
    Args:
        qatestcase: Single QA testcase string (e.g., "QA:Testcase_base_startup")
        wiki: Wiki connection object (optional, will create if None)
        release: Release number (optional, gets from current compose if None)
        compose: Compose name (optional, gets from current compose if None)
        milestone: Milestone (optional, gets from current compose if None)
        sections: List of section names to filter (optional, searches all if None)
        environment: Environment name (required)
        testtype: Test type name (default: "Cloud")
        production: Use production wiki (default: False)
        status: Status for new result ("pass", "fail", "warn") - required
        comment: Comment for new result (optional)
        bugs: Bugs for new result (optional)
        allow_duplicate: Allow duplicate results (default: False)
    
    Returns:
        dict: Dictionary containing:
            - testcase_found: bool indicating if testcase was found
            - result_added: bool indicating if result was added
    """
    
    # Validate required inputs
    if not environment:
        raise ValueError("Environment is required")
    if not status:
        raise ValueError("Status is required")
    
    # Get wiki connection and test type page using common function
    wiki, event, release, milestone, compose, page = get_wiki_connection(
        wiki=wiki, release=release, compose=compose, milestone=milestone,
        sections=sections, environment=environment, testtype=testtype,
        production=production
    )
    
    # Validate username
    if not wiki.username or not isinstance(wiki.username, str):
        raise ValueError("Wiki username is not set. Please ensure you are logged in.")
    username = wiki.username.lower()
    
    # Get all result rows - same pattern as get_testcases line 109
    tests = page.get_resultrows(statuses=["pass", "warn", "fail", "inprogress"])
    
    # Group by section - same pattern as get_testcases lines 111-114
    page_sections = page.results_sections
    testsecs = {t.secid for t in tests}
    page_sections = [s for s in page_sections if s["index"] in testsecs]
    
    # Find the testcase - search through sections like get_testcases
    test = None
    tag_patt = re.compile("<.*?>")
    
    for section in page_sections:
        try:
            # Ensure section is a dict and has required keys
            if not isinstance(section, dict) or "index" not in section:
                continue
                
            section_tests = [t for t in tests if t.secid == section["index"]]
            if section_tests:
                # Handle None case for section["line"] - same pattern as report_results_noninteractive.py line 87
                sec_line = section.get("line") or ""
                sec_line_clean = tag_patt.sub("", sec_line) if sec_line else ""
                
                # Filter by sections if provided - ensure sec_filter is not None
                # Convert sections to list if it's a single string
                sections_list = [sections] if isinstance(sections, str) else sections if sections else []
                if sections is None or any(
                    sec_filter and (str(sec_filter) in sec_line_clean or sec_line_clean in str(sec_filter))
                    for sec_filter in sections_list if sec_filter is not None
                ):
                    # Search for testcase in this section
                    for candtest in section_tests:
                        if candtest.testcase == qatestcase:
                            test = candtest
                            break
                    if test:
                        break
        except Exception as e:
            logging.debug(f"Error processing section: {e}")
            continue
    
    if not test:
        logging.warning(f"Testcase '{qatestcase}' not found")
        return {
            'testcase_found': False,
            'result_added': False
        }
    
    # Get environments - same as report_results.py line 367
    envs = list(test.results.keys())
    env = environment if environment in envs else None
    
    # Case-insensitive match
    if not env:
        env_lower = environment.lower()
        for env_name in envs:
            if env_name.lower() == env_lower:
                env = env_name
                logging.debug(f"Matched environment '{environment}' to '{env}'")
                break
    
    if not env:
        available_envs = ", ".join(envs) if envs else "none"
        raise ValueError(
            f"Environment '{environment}' not found for test case '{qatestcase}'. "
            f"Available: {available_envs}"
        )
    
    # Check existing results - same pattern as report_results.py lines 383-398
    results = test.results[env]
    if results:
        results_list = results if isinstance(results, list) else [results]
        myres = [r for r in results_list if r.user and isinstance(r.user, str) and r.user.lower() == username]
        if myres and not allow_duplicate:
            print(f"ERROR: Result already exists for user '{username}'")
            return {
                'testcase_found': True,
                'result_added': False
            }
        
        # If comment is provided, check if first result already has a comment
        # Only add comment if first result doesn't have one (only one comment should be added)
        if comment:
            first_result = results_list[0]
            if first_result.comment and first_result.comment.strip():
                # First result already has a comment, don't add another one
                logging.debug(f"First result already has comment: {first_result.comment}, skipping comment addition")
                comment = ""  # Don't add comment to new result
                logging.info(f"First result already has a comment, not adding new comment for {qatestcase}")
    
    # Format comment - same as report_result
    # wikitcms.result.Result expects empty string, not None
    if comment:
        comment = comment_string(comment, maxlen=250)
    else:
        comment = ""  # Use empty string instead of None
    
    # Ensure bugs is None or a list (wikitcms expects this)
    if bugs is not None and not isinstance(bugs, list):
        bugs = [bugs] if bugs else None
    
    # Validate that test and env are not None before proceeding
    if test is None:
        raise ValueError(f"Test object is None for testcase '{qatestcase}'")
    if env is None:
        raise ValueError(f"Environment is None for testcase '{qatestcase}'")
    
    # Create and add result - same pattern as report_results.py line 405
    # Ensure username is a string (not None)
    username_str = str(username) if username else ""
    res = wikitcms.result.Result(status, ("bot=true|" + username_str), bugs, comment)
    
    try:
        page.add_result(res, test, env)
        
        # Construct wiki URL
        wiki_host = "fedoraproject.org" if production else "stg.fedoraproject.org"
        page_name = page.name.replace(" ", "_")  # Replace spaces with underscores for URL
        wiki_url = f"https://{wiki_host}/wiki/{page_name}"
        
        return {
            'testcase_found': True,
            'result_added': True,
            'wiki_url': wiki_url
        }
    except Exception as e:
        import traceback
        error_msg = f"Error adding result: {e}"
        logging.error(error_msg)
        # Print traceback to stderr so it's always visible
        print(f"ERROR: {error_msg}", file=sys.stderr)
        print(f"Full traceback:", file=sys.stderr)
        traceback.print_exc(file=sys.stderr)
        # Also print debug info
        print(f"DEBUG: test={test}, env={env}, status={status}, username={username}, comment={comment}, bugs={bugs}", file=sys.stderr)
        # Re-raise with more context
        raise RuntimeError(f"Failed to add result for {qatestcase}: {e}") from e


def check_bot_results_exist(wiki=None, release=None, compose=None, milestone=None, environment=None, testtype="Cloud", production=False):
    """
    Check if any bot results exist in the wiki for the given test type.
    
    Args:
        wiki: Wiki connection object (optional, will create if None)
        release: Release number (optional, gets from current compose if None)
        compose: Compose name (optional, gets from current compose if None)
        milestone: Milestone (optional, gets from current compose if None)
        environment: Environment name (optional, for reference)
        testtype: Test type name (default: "Cloud")
        production: Use production wiki (default: False)
    
    Returns:
        bool: True if bot results are found, False otherwise
    """
    # Get the page to access test results
    wiki_conn, event, release, milestone, compose, page = get_wiki_connection(
        wiki=wiki, release=release, compose=compose, milestone=milestone,
        sections=None, environment=environment, testtype=testtype,
        production=production
    )
    
    # Get all result rows
    tests = page.get_resultrows(statuses=["pass", "warn", "fail", "inprogress"])
    
    # Check if there's at least one result with bot attribute set or 'bot=true' in the user field
    # If environment is specified, only check that environment; otherwise check all environments
    bot_found = False
    for test in tests:
        # Check all environments for this test, or filter by specified environment
        for env_name, env_results in test.results.items():
            # If environment is specified, only check that environment (case-insensitive)
            if environment:
                env_lower = environment.lower()
                if env_name.lower() != env_lower:
                    continue
            
            if env_results:
                results_list = env_results if isinstance(env_results, list) else [env_results]
                if results_list and len(results_list) > 0:
                    for result in results_list:
                        # Check bot attribute (boolean or string)
                        if hasattr(result, 'bot') and result.bot:
                            bot_found = True
                            logging.debug(f"Found bot result: testcase={test.testcase}, env={env_name}, user={result.user}")
                            break
                        # Check user field for 'bot=true' pattern (format: "bot=true|username")
                        user_str = str(result.user) if result.user else ''
                        if 'bot=true' in user_str.lower() or (user_str and 'bot' in user_str.lower() and '=' in user_str):
                            bot_found = True
                            logging.debug(f"Found bot result: testcase={test.testcase}, env={env_name}, user={result.user}")
                            break
                if bot_found:
                    break
        if bot_found:
            break
    
    # If bot is found in results, show who touched the wiki
    if bot_found:
        wiki_username = wiki.username if wiki.username else "unknown"
        # Construct wiki URL
        wiki_host = "fedoraproject.org" if production else "stg.fedoraproject.org"
        page_name = page.name.replace(" ", "_")  # Replace spaces with underscores for URL
        wiki_url = f"https://{wiki_host}/wiki/{page_name}"
        print(f"bot touched this wiki: user={wiki_username}")
        print(f"name={page.name}")
        print(f"link={wiki_url}")
    else:
        # Debug: show what was checked
        env_filter = f" (filtered by environment: {environment})" if environment else ""
        logging.debug(f"No bot results found in {len(tests)} testcases{env_filter}")
    
    return bot_found


def main():
    """main function to report validation results non-interactively."""
    parser = argparse.ArgumentParser(description="Report release validation results non-interactively.")
    parser.add_argument("--sections", "--section", default="x86_64", dest="sections",
                        help="Section to report results for (default: x86_64), e.g. x86_64 or aarch64")
    parser.add_argument("--production", action="store_true",
                        help="Use production wiki instead of staging (default: staging)")
    parser.add_argument("--debug", action="store_true",
                        help="Enable debug logging to show detailed information")
    parser.add_argument("--try", dest="try_mode", action="store_true",
                        help="Only check if results exist, don't add them. Prints 'RESULTS MISSING'")
    parser.add_argument("--comment", default="",
                        help="Comment to add to test results")
    parser.add_argument("--list_testcases", action="store_true",
                        help="Only list testcases and exit (don't process results)")
    parser.add_argument("--api-url", "--api_url", dest="api_url",
                        help="Testing Farm API URL (e.g., https://api.dev.testing-farm.io/v0.1/requests/<uuid>)")
    
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
    # sections is now a single string, convert to list for functions that expect a list
    sections_arg = args.sections
    # Functions expect sections as list or None, so convert single string to list
    sections_for_functions = [sections_arg] if sections_arg else None
    environment="EC2 (KVM)"
    testtype="Cloud"
    #TODO: from options when needed^^^

    # If --list_testcases option is set, check if any bot results exist, then exit
    if args.list_testcases:
        check_bot_results_exist(
            wiki=wiki,
            release=release,
            compose=compose,
            milestone=milestone,
            environment=environment,
            testtype=testtype,
            production=args.production
        )
        sys.exit(0)
    
    # List of sections to report results for (from command line)
    testcases = get_testcases(wiki=wiki, release=release, compose=compose, milestone=milestone, sections=sections_for_functions, environment=environment, testtype=testtype, production=args.production)
    
    # Check if api_url is provided (required when not using --list_testcases)
    if not args.list_testcases and not args.api_url:
        parser.error("--api-url is required when not using --list_testcases")
    
    # Fetch and cache XUnit XML, then match each testcase
    if args.api_url:
        xunit_cache = {}
        xunit_data = fetch_and_cache_xunit_xml(args.api_url, cache=xunit_cache)
        logging.debug(f"Overall: {xunit_data['overall']}, XUnit URL: {xunit_data['xunit_url']}")
        
        # Match each testcase from the testcases list
        wiki_urls = set()  # Collect unique wiki URLs
        comment_added = False  # Track if comment has been added to first result
        for qatestcase in testcases:
            match_result = match_qatestcase_with_fmf_plan_name(xunit_data, qatestcase, "cloud")
            if match_result['qatestcase_found']:
                result = match_result['testcase_result'] or 'unknown'
                print(f"Found: {qatestcase} - Result: {result} ({len(match_result['matching_test_plans'])} plans)")
                logging.debug(f"  Plans: {match_result['matching_test_plans']}")
                
                # Map XUnit result to wiki status
                # XUnit: "passed" -> wiki: "pass", "failed" -> wiki: "fail"
                wiki_status = "warn"  # default
                if result == "passed":
                    wiki_status = "pass"
                elif result == "failed":
                    wiki_status = "fail"
                
                # Add result to wiki using modify_testcase_result
                if not args.try_mode:
                    try:
                        # Only add comment to the first result that gets added
                        comment_to_use = ""
                        if not comment_added:
                            # Use comment if provided, otherwise use artifacts_url
                            if args.comment:
                                comment_to_use = args.comment
                            elif xunit_data.get('artifacts_url'):
                                comment_to_use = xunit_data.get('artifacts_url', '')
                        
                        add_result = modify_testcase_result(
                            qatestcase=qatestcase,
                            wiki=wiki,
                            release=release,
                            compose=compose,
                            milestone=milestone,
                            sections=sections_for_functions,
                            environment=environment,
                            testtype=testtype,
                            production=args.production,
                            status=wiki_status,
                            comment=comment_to_use,
                            bugs=None,
                            allow_duplicate=True, # Assuming allow_duplicate is True for non-interactive mode
                            artifacts_url=xunit_data.get('artifacts_url', '')
                        )
                        
                        # Mark comment as added if result was successfully added and comment was used
                        if add_result.get('result_added') and comment_to_use:
                            comment_added = True
                        if add_result.get('result_added'):
                            print(f"  ✓ Added result: {wiki_status} for {qatestcase}")
                            # Collect wiki URL if available
                            if add_result.get('wiki_url'):
                                wiki_urls.add(add_result.get('wiki_url'))
                        else:
                            logging.warning(f"  ✗ Failed to add result for {qatestcase}")
                    except Exception as e:
                        import traceback
                        logging.error(f"  ✗ Error adding result for {qatestcase}: {e}")
                        # Print full traceback to stderr
                        print(f"ERROR: Full traceback for {qatestcase}:", file=sys.stderr)
                        traceback.print_exc(file=sys.stderr)
                else:
                    logging.debug(f"  Try mode: Would add result {wiki_status} for {qatestcase}")
            else:
                logging.debug(f"Not found: {qatestcase}")
        
        # Print all wiki URLs where results were added
        if wiki_urls:
            print("\n" + "="*60)
            print("Wiki pages where results were added:")
            print("="*60)
            for wiki_url in sorted(wiki_urls):
                print(f"  {wiki_url}")
            print("="*60)




if __name__ == "__main__":
    main()

