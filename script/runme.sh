#!/bin/bash
for i in x86_64 aarch64;do
    arch=$i
    distro=$(python get_image_names.py | grep rawhide | grep $arch | gawk -F': ' '{ print $2 }')
    if python report_results_noninteractive.py --sections $arch --try ; then
        tft_output=$(./tft-wait.py --git-url https://github.com/psklenar/fedoraQA.git --compose $distro --plan '/cloud/' --debug 2>&1 | tee /dev/tty)
        artifacts_url=$(echo "$tft_output" | grep -E '^artifacts_url=' | cut -d'=' -f2-)
        python report_results_noninteractive.py --sections $arch --comment "$artifacts_url"
    fi
done

