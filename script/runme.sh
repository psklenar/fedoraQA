#!/bin/bash

# Script to run Testing Farm tests for multiple architectures
# For each architecture, it checks if results exist, runs tests, and reports results

for ARCH in aarch64 x86_64; do
    echo "=========================================="
    echo "Processing architecture: $ARCH"
    echo "=========================================="
    
    # Get the distro image name for this architecture
    DISTRO=$(python get_image_names.py | grep rawhide | grep $ARCH | gawk -F': ' '{ print $2 }')
    
    # Check if results already exist for this architecture
    if python report_results_noninteractive.py --sections $ARCH --try ; then
        echo "Results already exist for $ARCH, skipping..."
        continue
    fi
    
    # Run Testing Farm test and capture output
    echo "Running Testing Farm test for $ARCH..."
    TFT_OUTPUT=$(./tft-wait.py \
        --git-url https://github.com/psklenar/fedoraQA.git \
        --compose "$DISTRO" \
        --plan '/cloud/' \
        --arch "$ARCH" \
        --debug \
        2>&1 | tee /dev/tty)
    TFT_EXIT_CODE=$?
    
    # Extract and set variables from tft-wait.py output
    eval $(echo "$TFT_OUTPUT" | grep -E '^(FINAL_STATE|DURATION|ARTIFACTS_URL|RESULTS)=')
    
    # Check if tft-wait.py executed successfully
    if [ $TFT_EXIT_CODE -ne 0 ]; then
        echo "ERROR: tft-wait.py failed with exit code $TFT_EXIT_CODE"
        exit 1
    fi
    
    # Verify that required variables were set
    if [ -z "$ARTIFACTS_URL" ] || [ -z "$DURATION" ] || [ -z "$RESULTS" ]; then
        echo "ERROR: Required variables not set:"
        echo "  ARTIFACTS_URL: ${ARTIFACTS_URL:-NOT SET}"
        echo "  DURATION: ${DURATION:-NOT SET}"
        echo "  RESULTS: ${RESULTS:-NOT SET}"
        exit 1
    fi
    
    # Report the test results
    echo "Reporting results for $ARCH..."
    echo "  Artifacts URL: $ARTIFACTS_URL"
    echo "  Duration: $DURATION"
    echo "  Results: $RESULTS"
    
    python report_results_noninteractive.py \
        --sections "$ARCH" \
        --comment "$ARTIFACTS_URL" \
        --status "$RESULTS"
    
    echo "Completed processing for $ARCH"
    echo ""
done

echo "All architectures processed successfully!"

