#!/usr/bin/python3
# Requires testing-farm package
import argparse
import logging
import os
import re
import subprocess
import sys
import time
import requests

ERR_LOGFILE = 'fedora-err-log.txt'


def fetch_api_data(api_url, max_retries=3, retry_interval=10):
    """
    Fetch data from API with retry logic for unstable networks.
    
    Args:
        api_url: The API URL to fetch
        max_retries: Maximum number of retry attempts (default: 3)
        retry_interval: Seconds to wait between retries (default: 10)
    
    Returns:
        dict: The JSON data from the API
    
    Raises:
        requests.exceptions.RequestException: If all retries fail
    """
    for attempt in range(1, max_retries + 1):
        try:
            response = requests.get(api_url)
            response.raise_for_status()
            return response.json()
        except requests.exceptions.RequestException as e:
            if attempt < max_retries:
                logging.warning(f'API request failed (attempt {attempt}/{max_retries}): {e}, retrying in {retry_interval} seconds')
                time.sleep(retry_interval)
            else:
                logging.error(f'API request failed after {max_retries} attempts: {e}')
                raise


###########################################################
# Parse the output
#eval $(./tft-wait.py --git-url <url> --compose <compose> 2>/dev/null | grep -E '^(final_state|duration|artifacts_url)=')

# Or source it
#source <(./tft-wait.py --git-url <url> --compose <compose> 2>&1 | grep -E '^(final_state|duration|artifacts_url)=')

# Then use the variables
#echo "State: $final_state"
#echo "Duration: $duration seconds"
#echo "Artifacts: $artifacts_url"
###########################################################

def wait_for_completion(api_url, check_interval, deadline_hours):
    """
    Wait for Testing Farm request to complete by polling the API.
    
    Args:
        api_url: The Testing Farm API URL to poll
        check_interval: Time in seconds between checks
        deadline_hours: Maximum time to wait in hours
    
    Returns:
        tuple: (final_state, duration_seconds)
    """
    deadline_seconds = deadline_hours * 3600
    start_time = time.time()
    
    logging.info(f'Waiting for request to complete: {api_url}')
    logging.info(f'Checking every {check_interval} seconds, deadline: {deadline_hours} hours')
    
    while True:
        elapsed = time.time() - start_time
        
        if elapsed >= deadline_seconds:
            logging.warning(f'Deadline of {deadline_hours} hours reached')
            # Get final state before returning
            try:
                data = fetch_api_data(api_url)
                final_state = data.get('state', 'unknown')
                logging.warning(f'Final state at deadline: {final_state}')
                return (final_state, elapsed)
            except Exception as e:
                logging.error(f'Failed to get final state: {e}')
                return ('timeout', elapsed)
        
        try:
            data = fetch_api_data(api_url)
            state = data.get('state', 'unknown')
            
            logging.info(f'Current state: {state} (elapsed: {elapsed/60:.1f} minutes)')
            
            if state == 'complete':
                logging.info(f'Request completed successfully! Total time: {elapsed/60:.1f} minutes')
                return (state, elapsed)
            elif state in ['error', 'failed', 'cancelled']:
                logging.warning(f'Request ended with state: {state}')
                return (state, elapsed)
            
            # Wait before next check
            time.sleep(check_interval)
            
        except requests.exceptions.RequestException as e:
            logging.warning(f'Error polling API: {e}, retrying in {check_interval} seconds')
            time.sleep(check_interval)
        except Exception as e:
            logging.error(f'Unexpected error: {e}')
            return ('error', elapsed)


def get_artifacts_url(api_url):
    """
    Get the artifacts URL from the Testing Farm API response.
    
    Args:
        api_url: The Testing Farm API URL to query
    
    Returns:
        str: The artifacts URL, or None if not found
    """
    try:
        data = fetch_api_data(api_url)
        
        # Navigate to run.artifacts in the JSON structure
        run_data = data.get('run', {})
        artifacts_url = run_data.get('artifacts')
        
        if artifacts_url:
            logging.info(f'Artifacts URL: {artifacts_url}')
            return artifacts_url
        else:
            logging.warning('No artifacts URL found in API response')
            return None
            
    except requests.exceptions.RequestException as e:
        logging.error(f'Error fetching API data: {e}')
        return None
    except Exception as e:
        logging.error(f'Unexpected error getting artifacts URL: {e}')
        return None


def test_request(git_url, compose, arch, plan=None):
    # Check for required API token
    api_token = os.environ.get('TESTING_FARM_API_TOKEN')
    if not api_token:
        logging.error('TESTING_FARM_API_TOKEN environment variable is not set')
        raise ValueError('TESTING_FARM_API_TOKEN environment variable is required')
    
    stdout = ''
    try:
        logging.debug(f'Sending test request for: {git_url}')

        cmd = [
            'testing-farm', 'request',
            '--no-wait',
            '--git-url', git_url,
            '--git-ref', 'main',
            '--test-type', 'fmf',
            '--arch', arch,
        ]
        if plan:
            cmd.extend(['--plan', plan])
        cmd.extend(['--compose', compose])
        logging.debug(f'TFT Command: {cmd}')
        request = subprocess.Popen(cmd,
                                   stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                   shell=False, close_fds=True)
        stdout, stderr = request.communicate()
        
        # Sleep to ensure files are ready on unstable machines
        time.sleep(10)
        
        if request.returncode != 0:
            error_msg = stderr.decode('utf-8') if stderr else ''
            stdout_msg = stdout.decode('utf-8') if stdout else ''
            combined_error = error_msg or stdout_msg or 'Unknown error'
            raise ValueError(f"testing-farm command failed with return code {request.returncode}: {combined_error}")
        
        with open(os.path.join('.', ERR_LOGFILE), 'a+') as err_file:
            if stderr:
                logging.debug(f'{stderr.decode("utf-8")}')

        api_urls = re.findall(r'https://api.*', str(stdout.decode('utf-8')))
        if not api_urls:
            raise ValueError("No API URL found in testing-farm output")
        request_api_url = api_urls[0].split('[0')[0].strip()
        logging.debug(f'Request for: {git_url} done, api url: {request_api_url}')
    except Exception as e:
        if stdout:
            logging.debug(str(stdout.decode('utf-8')))
        logging.debug(f'Request for: {git_url} failed, exception: {e}')
        return None
    return request_api_url

def get_results(api_url):
    """
    Retrieve the 'overall' result from the Testing Farm API request.

    Args:
        api_url (str): The API request URL (e.g., https://api.testing-farm.io/v0.1/requests/<uuid>).

        Returns:
            str: The value of 'result["overall"]', e.g., 'passed', 'failed', or 'NOTFOUND' if not found or error.
    """
    try:
        data = fetch_api_data(api_url)
        result = data.get("result", {})
        overall = result.get("overall")
        if overall is None:
            return "warn"
        # Normalize "failed" to "fail"
        if overall == "failed":
            return "fail"
        # Normalize "passed" to "pass"
        if overall == "passed":
            return "pass"
        return overall
    except Exception as e:
        logging.debug(f"Failed to get results from {api_url}: {e}")
        return "warn"

def main():
    """
    Main function to trigger a test request using Testing Farm.
    Parses arguments using argparse.
    """
    parser = argparse.ArgumentParser(description="Trigger a Testing Farm test request.")
    parser.add_argument("--git-url", dest="git_url", help="The Git repository URL for the test.")
    parser.add_argument("--compose", help="The compose to test against.")
    parser.add_argument("--check-interval", type=int, default=300, help="Seconds between checks when waiting (default: 300 = 5 minutes).")
    parser.add_argument("--deadline-hours", type=float, default=10.0, help="Maximum hours to wait (default: 10).")
    parser.add_argument("--plan", dest="plan", help="The plan to test against.")
    parser.add_argument("--debug", action="store_true", help="Enable debug logging.")
    parser.add_argument("--arch", dest="arch", help="The architecture to test against.")
    args = parser.parse_args()

    # Optionally set debug flag
    global DEBUG
    DEBUG = args.debug
    logging.getLogger().setLevel(logging.DEBUG if DEBUG else logging.INFO)

    # Submit a new request
    if not args.git_url or not args.compose:
        parser.error("--git-url and --compose are required when submitting a new request")
    
    overall_start_time = time.time()
    result_url = test_request(args.git_url, args.compose, args.arch, args.plan)
    if result_url:
        logging.info(f'Test request submitted successfully! API URL: {result_url}')
        final_state, _ = wait_for_completion(result_url, args.check_interval, args.deadline_hours)
        logging.info(f'Final state: {final_state}')
        artifacts_url = get_artifacts_url(result_url)
        results = get_results(result_url)
        # Calculate total duration in hours
        total_duration_seconds = time.time() - overall_start_time
        total_duration_hours = total_duration_seconds / 3600
        
        # Output in bash-parsable format
        print(f"final_state={final_state}")
        print(f"duration={total_duration_hours:.2f}h")
        if artifacts_url:
            print(f"artifacts_url={artifacts_url}")
        else:
            print("artifacts_url=")
        print("results=", results)

        sys.exit(0 if final_state == 'complete' else 1)
    else:
        logging.error('Test request failed.')
        print("final_state=failed")
        print("duration=0.00h")
        print("artifacts_url=")
        print("results=warn")
        sys.exit(1)

if __name__ == "__main__":
    main()