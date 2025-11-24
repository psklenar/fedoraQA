#!/usr/bin/env python3
"""
Get image_name from datagrepper for the last 3? Fedora versions.
Returns image_name for both x86_64 and aarch64 architectures.
"""

from datetime import datetime, timezone, timedelta

import fedfind.helpers


def query_datagrepper(topic, start, end, limit=100):
    """Query datagrepper for messages matching a topic.

    Args:
        topic: The message topic to search for (e.g., "aws.nightly.Cloud_Base.x86_64")
    
    Returns:
        A list of message dictionaries, sorted by timestamp (newest first)
    """
    url = "https://apps.fedoraproject.org/datagrepper/raw?"
    url += f"topic={topic}"
    url += f"&start={start.timestamp()}&end={end.timestamp()}"
    url += f"&rows_per_page={limit}"
    
    json_data = fedfind.helpers.download_json(url)
    msgs = json_data.get("raw_messages", [])
    
    # Handle pagination
    total_pages = json_data.get("pages", 1)
    if total_pages > 1 and len(msgs) < limit:
        for page_num in range(2, min(total_pages + 1, 10)):
            if len(msgs) >= limit:
                break
            newurl = f"{url}&page={page_num}"
            newjson = fedfind.helpers.download_json(newurl)
            msgs.extend(newjson.get("raw_messages", []))
            if len(msgs) >= limit:
                break
    
    return msgs[:limit] if msgs else []


def get_image_names_for_version(version, arch, days_back=30):
    """Get the latest image_name for a specific Fedora version and architecture."""
    end_date = datetime.now(timezone.utc)
    start_date = end_date - timedelta(days=days_back)
    
    # Rawhide uses different topic than stable versions
    if version == "Rawhide":
        topics = [
            f"org.fedoraproject.prod.fedora_image_uploader.published.v1.aws.rawhide.Cloud_Base.{arch}",
            f"org.fedoraproject.prod.fedora_image_uploader.published.v1.aws.nightly.Cloud_Base.{arch}"
        ]
    else:
        topics = [f"org.fedoraproject.prod.fedora_image_uploader.published.v1.aws.nightly.Cloud_Base.{arch}"]
    
    latest_image_name = None
    latest_timestamp = 0
    
    for topic in topics:
        messages = query_datagrepper(topic, start_date, end_date, limit=100)
        
        for msg in messages:
            if 'msg' in msg:
                msg_data = msg['msg']
                image_name = msg_data.get('image_name')
                if image_name:
                    matches = False
                    if version == "Rawhide":
                        if "Rawhide" in image_name or "rawhide" in image_name.lower():
                            matches = True
                    else:
                        if f"-{version}-" in image_name or f"-{version}." in image_name:
                            matches = True
                    
                    if matches:
                        timestamp = msg.get('timestamp', 0)
                        if timestamp > latest_timestamp:
                            latest_timestamp = timestamp
                            latest_image_name = image_name
    
    return [latest_image_name] if latest_image_name else []


def get_last_three_versions():
    """Get the last 3 Fedora versions: Rawhide, current branched, and previous."""
    current_branched = fedfind.helpers.get_current_release(branched=True)
    versions = ["Rawhide", current_branched, current_branched - 1]
    return versions


def main():
    """Get image_name for last 3 Fedora versions and display results."""
    versions = get_last_three_versions() #  ["Rawhide", current_branched, current_branched - 1]
    results = {} #  {version: {arch: [image_name]}}
    
    for version in versions:
        results[version] = {} # {version: {arch: [image_name]}}
        for arch in ['x86_64', 'aarch64']:
            image_names = get_image_names_for_version(version, arch) 
            results[version][arch] = image_names
    
    # Determine which version is current (the middle one: versions[1])
    # versions = ["Rawhide", current_branched, current_branched - 1]
    # Example: ["Rawhide", 43, 42] - so 43 is current
    current_version = versions[1]
    
    # Print into terminal in bash-parsable format
    for version in versions:
        for arch in ['x86_64', 'aarch64']:
            image_names = results[version].get(arch, [])
            if image_names:
                # Build the output string
                if version == "Rawhide":
                    # Rawhide format: rawhide, x86_64: image_name
                    version_str = "rawhide"
                    print(f"{version_str}, {arch}: {image_names[0]}")
                else:
                    # Numeric version format: f43, current, x86_64: image_name
                    version_str = f"f{version}"
                    # Determine label: "current" or "last"
                    if version == current_version:
                        label = "current"
                    else:
                        label = "last"
                    print(f"{version_str}, {label}, {arch}: {image_names[0]}")
    
    return results


if __name__ == "__main__":
    image_names_results = main()

