import os
import json
import requests
import oss2
from github import Github
import base64
import time
from datetime import datetime

remaining_count = 0

REPO_OWNER = "xxTree"
REPO_NAME = "ManifestAutoUpdate"
TOKEN = os.environ["KEY"]
OSS_ACCESS_KEY_ID = os.environ["OSS_ACCESS_KEY_ID"]
OSS_ACCESS_KEY_SECRET = os.environ["OSS_ACCESS_KEY_SECRET"]
OSS_BUCKET_NAME = "zqb-client"
OSS_ENDPOINT = "oss-cn-beijing.aliyuncs.com"
OSS_BASE_DIR = "zqb/branches/data"

headers = {
    "Authorization": f"token {TOKEN}"
}

def check_remaining_count(github):
    global remaining_count
    rate_limit = github.get_rate_limit()
    remaining = rate_limit.core.remaining
    reset_time = rate_limit.core.reset
    reset_time_timestamp = reset_time.timestamp()
    reset_time_datetime = datetime.fromtimestamp(reset_time_timestamp)

    if remaining <= 10:
        wait_time = reset_time_datetime - datetime.now()
        wait_seconds = wait_time.total_seconds()
        print(f"暂停程序 {wait_seconds} 秒,直到 {reset_time_datetime}。现在的时间是 {datetime.now()}")
        time.sleep(wait_seconds + 10)
    else:
        print(f"剩余请求次数: {remaining}")
        print(f"限制将在 {reset_time_datetime} 重置,现在的时间是 {datetime.now()}")
        remaining_count = remaining

def upload_to_oss(branch, file_name, content):
    auth = oss2.Auth(OSS_ACCESS_KEY_ID, OSS_ACCESS_KEY_SECRET)
    bucket = oss2.Bucket(auth, OSS_ENDPOINT, OSS_BUCKET_NAME)
    object_name = f"{OSS_BASE_DIR}/{branch}/{file_name}"
    result = bucket.put_object(object_name, content)
    return result.status == 200

def update_api(data):
    api_url = "http://39.105.28.227:80/server/api/remote/setData"
    headers = {
        "Content-Type": "application/json"
    }
    response = requests.post(api_url, headers=headers, data=json.dumps(data))
    return response.status_code

def fetch_data(repo, branch, github):
    global remaining_count
    if remaining_count <= 1:
        check_remaining_count(github)
    branch_obj = repo.get_branch(branch)
    remaining_count = remaining_count - 1
    commit_sha = branch_obj.commit.sha
    if remaining_count <= 1:
        check_remaining_count(github)
    contents = repo.get_contents("", ref=branch)
    remaining_count = remaining_count - 1

    files_data = []
    for item in contents:
        #file_content = base64.b64decode(item.content)
        file_name = item.path.split("/")[-1]
        #files_data.append({"name": file_name, "content": file_content})
        files_data.append(file_name)
        
    status_code = update_api({"branch": branch,"sha": commit_sha,"paths": files_data})
    if status_code == 200:
        print(f"API updated successfully for branch {branch}.")
    else:
        print(f"Failed to update API for branch {branch} with status code: {status_code}")
    """
    for data in files_data:
        file_name = data["name"]
        content = data["content"]

        uploaded = upload_to_oss(branch, file_name, content)

        if uploaded:
            print(f"Uploaded {file_name} to OSS for branch {branch}.")
        else:
            print(f"Failed to upload {file_name} to OSS for branch {branch}.")
    """

if __name__ == "__main__":
    github = Github(TOKEN)
    check_remaining_count(github)
    
    repo = github.get_repo(f"{REPO_OWNER}/{REPO_NAME}")
    remaining_count = remaining_count - 1

    if remaining_count <= 1:
        check_remaining_count(github)
    all_branches = list(repo.get_branches())
    remaining_count = remaining_count - 1

    for branch in all_branches:
        if branch.name.isdigit() and int(branch.name) > 0:
            print(f"当前处理 {branch.name} 分支")
            fetch_data(repo, branch.name, github)


