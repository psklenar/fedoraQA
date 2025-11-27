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

import wikitcms.wiki

import wikitcms.result


def comment_string(string, maxlen=250):
    """
    c&p from relval/report_results.py, it's the only function from that file.
    Take 'string' and wrap it in <ref> </ref> if it's not the empty
    string. Raise a ValueError if it's longer than maxlen.
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


def report_result(
    wiki,
    release,
    compose,
    testtype,
    testcase,
    environment,
    status,
    milestone="",
    section=None,
    bugs=None,
    comment="",
    dist="Fedora",
    allow_duplicate=False,
    try_mode=False,
):
    """Non-interactive function to report a validation test result.

    This function reports a test result without prompting the user for
    any input. All required information must be provided as parameters.

    """
    if not wiki.username or not isinstance(wiki.username, str):
        raise ValueError("Wiki username is not set. Please ensure you are logged in.")
    username = wiki.username.lower()

    # Format comment
    if comment:
        comment = comment_string(comment, maxlen=250)

    # Get the validation event
    event = wiki.get_validation_event(
        release=release, milestone=milestone, compose=compose, dist=dist
    )

    # Find the test type page
    page = [pag for pag in event.result_pages if pag.testtype == testtype][0]

    # Get all result rows
    tests = page.get_resultrows(statuses=["pass", "warn", "fail", "inprogress"])

    # Get sections and find the matching section
    sections = page.results_sections
    testsecs = {t.secid for t in tests}
    sections = [s for s in sections if s["index"] in testsecs]

    # Find section by name (strip HTML tags for comparison)
    tag_patt = re.compile("<.*?>")
    section_obj = None
    for sec in sections:
        sec_line_clean = tag_patt.sub("", sec["line"])
        if section in sec_line_clean or sec_line_clean in section:
            section_obj = sec
            break

    # Find tests for the selected section
    section_tests = [t for t in tests if t.secid == section_obj["index"]] if section_obj else []

    # Find the test case by exact match
    test = None
    for candtest in section_tests:
        if candtest.testcase == testcase:
            test = candtest
            break

    # Find the environment by exact match, then try case-insensitive match
    envs = list(test.results.keys()) if test else []
    env = environment if environment in envs else None
    
    # If exact match not found, try case-insensitive match
    if test and not env:
        env_lower = environment.lower()
        for env_name in envs:
            if env_name.lower() == env_lower:
                env = env_name
                logging.debug(f"Matched environment '{environment}' to '{env}' (case-insensitive)")
                break

    # If environment not found, provide helpful error message
    if test and not env:
        available_envs = ", ".join(envs) if envs else "none"
        raise ValueError(
            f"Environment '{environment}' not found for test case '{testcase}'. "
            f"Available environments: {available_envs}"
        )

    # If --try mode, only check for results and exit script
    if try_mode:
        if not test or not env:
            print("RESULTS MISSING")
            sys.exit(0)
        current_result = test.results.get(env)
        if current_result:
            # Results found, don't save and report RESULTS MISSING
            print("RESULTS FOUND")
            sys.exit(1)
        else:
            # No results found, don't save and report NO RESULTS
            print("RESULTS MISSING")
            sys.exit(0)

    # Validate that test exists before proceeding
    if not test:
        raise ValueError(f"Test case '{testcase}' not found in section '{section}'")
    # Note: env validation is done earlier with helpful error message

    # Final validation of username before creating result
    if not username or not isinstance(username, str) or not username.strip():
        raise ValueError(f"Invalid username: '{username}'. Wiki username: '{wiki.username}'")

    # Create the result object
    res = wikitcms.result.Result(status, username, bugs, comment)

    # Download and print current results for debugging before adding new result
    current_result = test.results.get(env)

    logging.debug(f"Current results for testcase '{testcase}', environment '{env}':")
    if current_result:
        # Handle both list and single result cases
        results_list = current_result if isinstance(current_result, list) else [current_result]
        for idx, result in enumerate(results_list):
            logging.debug(f"  Result #{idx + 1}:")
            logging.debug(f"    Status: {result.status}")
            logging.debug(f"    User: {result.user}")
            logging.debug(f"    Bugs: {result.bugs}")
            logging.debug(f"    Comment: {result.comment}")
            # Check if this result belongs to the logged-in user
            if result.user and isinstance(result.user, str) and result.user.lower() == username:
                print(f"ERROR: Result already exists for user '{username}'. Exiting script.")
                sys.exit(1)
    else:
        logging.debug("  No existing result found")
    logging.debug(f"Adding new result - Status: {status}, User: {username}, Bugs: {bugs}, Comment: {comment}")

    # Report the result
    try:
        page.add_result(res, test, env)
    except AttributeError as e:
        if "'NoneType' object has no attribute 'lower'" in str(e):
            # This error suggests something inside wikitcms is trying to call .lower() on None
            # Let's check if username is properly set
            if not username:
                raise ValueError("Username is None when trying to add result. This should not happen.")
            raise ValueError(f"Error adding result: {e}. Username: {username}, Test: {test}, Env: {env}")
        raise


def report_testcase_list(
    wiki,
    release,
    compose,
    testtype,
    testcase_list,
    environment,
    status,
    milestone="",
    section=None,
    bugs=None,
    comment="",
    dist="Fedora",
    allow_duplicate=False,
    try_mode=False,
):
    """Report results for a list of test cases.

    This function takes a list of test case names and reports the same result
    for all of them.

    """
    if not testcase_list:
        print("No test cases provided in the list.")
        return []

    # Handle both old format (strings) and new format (tuples)
    # Convert to list of tuples if needed
    normalized_testcases = []
    for item in testcase_list:
        if isinstance(item, tuple):
            normalized_testcases.append(item)
        else:
            # Old format: just a string, default to no comment
            normalized_testcases.append((item, False))

    if not try_mode:
        print(f"Reporting results for {len(normalized_testcases)} test case(s):")
        for testcase_name, _ in normalized_testcases:
            print(f"  - {testcase_name}")

    reported = []
    failed = []

    for testcase_name, use_comment in normalized_testcases:
        try:
            # Use comment only if use_comment is True, otherwise set to empty string
            # Both True and False cases will be reported, only True gets comment
            testcase_comment = comment if use_comment else ""
            logging.debug(f"Reporting {testcase_name} with comment={'set' if testcase_comment else 'None'}")
            report_result(
                wiki=wiki,
                release=release,
                compose=compose,
                testtype=testtype,
                testcase=testcase_name,
                environment=environment,
                status=status,
                milestone=milestone,
                section=section,
                bugs=bugs,
                comment=testcase_comment,
                dist=dist,
                allow_duplicate=allow_duplicate,
                try_mode=try_mode,
            )
            reported.append(testcase_name)
            print(f"✓ Reported result for {testcase_name}")
        except Exception as err:
            failed.append((testcase_name, str(err)))
            print(f"✗ Failed to report result for {testcase_name}: {err}")

    print(f"\nSummary: {len(reported)} succeeded, {len(failed)} failed")
    if failed:
        print("Failed test cases:")
        for testcase, error in failed:
            print(f"  - {testcase}: {error}")

    return reported


def main():
    """Example main function demonstrating how to use report_result."""
    parser = argparse.ArgumentParser(description="Report release validation results non-interactively.")
    parser.add_argument("--sections", nargs="+", default=["x86_64"],
                        help="List of sections to report results for (default: x86_64), e.g. x86_64 aarch64")
    parser.add_argument("--production", action="store_true",
                        help="Use production wiki instead of staging (default: staging)")
    parser.add_argument("--debug", action="store_true",
                        help="Enable debug logging to show detailed information")
    parser.add_argument("--try", dest="try_mode", action="store_true",
                        help="Only check if results exist, don't add them. Prints 'NO RESULTS' or 'RESULTS MISSING'")
    parser.add_argument("--comment", default="",
                        help="Comment to add to test results")
    
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
    # this is a handy way to get whichever is set, and if for some
    # crazy reason both are set it'll prefer 'T/RCx' to 'YYYYMMDD',
    # which we probably want.
    compose = max(curr["compose"], curr["date"])
    # List of test cases to report results for
    # Format: (testcase_name, use_comment)
    # use_comment=True means the testcase will get the comment, False means comment=None
    testcase_list = [
        ("QA:Testcase_base_startup", True),
        ("QA:Testcase_base_reboot_unmount", False),
        ("QA:Testcase_base_system_logging", False),
        ("QA:Testcase_base_update_cli", False),
        ("QA:Testcase_package_install_remove", False),
##        ("QA:Testcase_base_artwork_release_identification", False),
##        ("QA:Testcase_base_edition_self_identification", False),
        ("QA:Testcase_base_services_start", False),
        ("QA:Testcase_base_selinux", False),
        ("QA:Testcase_base_service_manipulation", False),
    ]

    # List of sections to report results for (from command line)
    sections = args.sections

    # Report results for all QA:testcases in the list for each section
    all_reported = []
    for section in sections:
        if not args.try_mode:
            print(f"\n{'='*60}")
            print(f"Processing section: {section}")
            print(f"{'='*60}")
        try:
            reported = report_testcase_list(
                wiki=wiki,
                release=release,
                compose=compose,
                testtype="Cloud",
                testcase_list=testcase_list,
                section=section,
                environment="EC2 (KVM)",
                status="pass",
                milestone=milestone,
                bugs=None,
                comment=args.comment,
                allow_duplicate=True,
                try_mode=args.try_mode
            )
            all_reported.extend(reported)
            print(f"Successfully reported results for {len(reported)} test case(s) in section {section}!")
        except ValueError as err:
            print(f"Error in section {section}: {err}", file=sys.stderr)
        except IndexError as err:
            print(f"Error in section {section}: {err}", file=sys.stderr)
    
    print(f"\n{'='*60}")
    print(f"Overall summary: {len(all_reported)} test case results reported across all sections")
    print(f"{'='*60}")


if __name__ == "__main__":
    main()

