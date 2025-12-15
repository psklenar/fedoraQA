#!/bin/bash

# Script to run Testing Farm tests for multiple architectures
# For each architecture, it checks if results exist, runs tests, and reports results
# Runs architectures in parallel

# Create temporary directory for logs organized by date
DATE_DIR=$(date +%Y%m%d)
TMP_DIR="/tmp/fedoraqa/$DATE_DIR"
mkdir -p "$TMP_DIR"
echo "Log directory: $TMP_DIR"

process_arch() {
    local ARCH=$1
    local LOG_DIR="$TMP_DIR/$ARCH"
    mkdir -p "$LOG_DIR"
    
    local LOG_FILE="$LOG_DIR/output.log"
    
    (
        echo "=========================================="
        echo "Processing architecture: $ARCH"
        echo "Log directory: $LOG_DIR"
        echo "=========================================="
        
        # Get the distro image name for this architecture
        DISTRO=$(python get_image_names.py | grep rawhide | grep $ARCH | gawk -F': ' '{ print $2 }')
        
        # Check if bot results already exist for this architecture
        if python report_results_noninteractiveNEW.py --section $ARCH --list_testcases 2>&1 | grep -q 'bot touched this wiki' ; then
            echo "Bot results already exist for $ARCH, skipping..."
            exit 0
        fi
        
        # Run Testing Farm test and capture output
        echo "Running Testing Farm test for $ARCH..."
        TFT_OUTPUT=$(./tft-wait.py \
            --git-url https://github.com/psklenar/fedoraQA.git \
            --compose "$DISTRO" \
            --plan '/cloud/' \
            --arch "$ARCH" \
            --debug \
            2>&1 | tee "$LOG_DIR/tft-wait.log")
        TFT_EXIT_CODE=$?

        # Extract and set variables from tft-wait.py output
        eval $(echo "$TFT_OUTPUT" | grep -E '^(FINAL_STATE|DURATION|ARTIFACTS_URL|API_URL|RESULTS)=')
        
        
        # Check if tft-wait.py executed successfully
        if [ $TFT_EXIT_CODE -ne 0 ]; then
            echo "ERROR: tft-wait.py failed with exit code $TFT_EXIT_CODE for $ARCH"
            exit 1
        fi
        
        python report_results_noninteractiveNEW.py \
            --sections "$ARCH" \
            --api-url "$API_URL" \
            2>&1 | tee "$LOG_DIR/report-results.log"
        
        if [ ${PIPESTATUS[0]} -ne 0 ]; then
            exit 1
        fi
        
        echo "Completed processing for $ARCH"
    ) > "$LOG_FILE" 2>&1
    
    local EXIT_CODE=$?
    echo "[$ARCH] Logs: $LOG_DIR (exit code: $EXIT_CODE)"
    return $EXIT_CODE
}

# Run architectures in parallel
PIDS=()
for ARCH in aarch64 x86_64; do
    process_arch "$ARCH" &
    PIDS+=($!)
done

# Wait for all background processes to complete and check exit codes
FAILED=0
for PID in "${PIDS[@]}"; do
    wait $PID
    if [ $? -ne 0 ]; then
        FAILED=1
    fi
done

# Exit with error if any process failed
if [ $FAILED -ne 0 ]; then
    echo "ERROR: One or more architectures failed"
    echo "Check logs in: $TMP_DIR"
    exit 1
fi

echo "All architectures processed successfully!"
echo "Logs available in: $TMP_DIR"

