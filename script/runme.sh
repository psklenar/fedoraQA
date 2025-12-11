#!/bin/bash

# Script to run Testing Farm tests for multiple architectures
# For each architecture, it checks if results exist, runs tests, and reports results

for ARCH in aarch64 x86_64; do
    echo "=========================================="
    echo "Processing architecture: $ARCH"
    echo "=========================================="
    
    # Get the distro image name for this architecture
    DISTRO=$(python get_image_names.py | grep rawhide | grep $ARCH | gawk -F': ' '{ print $2 }')
    
    # Check if bot results already exist for this architecture
    if python report_results_noninteractiveNEW.py --section $ARCH --list_testcases 2>&1 | grep -q 'bot touched this wiki' ; then
        echo "Bot results already exist for $ARCH, skipping..."
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
    
    
    # Check if tft-wait.py executed successfully
    if [ $TFT_EXIT_CODE -ne 0 ]; then
        echo "ERROR: tft-wait.py failed with exit code $TFT_EXIT_CODE"
        exit 1
    fi
    


    
    python report_results_noninteractiveNEW.py \
        --sections "$ARCH" \
        --api-url "$API_URL" \
    
    echo "Completed processing for $ARCH"
    echo ""
done

echo "All architectures processed successfully!"

