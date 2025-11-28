#!/bin/bash
for i in aarch64 x86_64;do
    arch=$i
    distro=$(python get_image_names.py | grep rawhide | grep $arch | gawk -F': ' '{ print $2 }')
    if python report_results_noninteractive.py --sections $arch --try ; then
        tft_output=$(./tft-wait.py --git-url https://github.com/psklenar/fedoraQA.git --compose $distro --plan '/cloud/' --arch $i --debug 2>&1 | tee /dev/tty)
        if [ $? -ne 0 ]; then
            echo "Error: tft-wait.py failed"
            exit 1
        fi
        artifacts_url=$(echo "$tft_output" | grep -E '^artifacts_url=' | cut -d'=' -f2-)
        overall_result=$(echo "$tft_output" | grep -E '^results=' | cut -d'=' -f2-)

        if [ -z "$artifacts_url" ]; then
            echo "Error: Failed to extract artifacts_url from tft-wait.py output"
            exit 1
        fi
        python report_results_noninteractive.py --sections $arch --comment "$artifacts_url" --status $overall_result
    fi
done

