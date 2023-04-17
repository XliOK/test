import os
import re
import json
import subprocess
import requests
import vdf
import shutil
import tarfile
import time

from io import BytesIO
from pathlib import Path
from urllib.request import urlretrieve
from typing import Dict, Any, List, Tuple
from github import Github
from datetime import datetime

APP_ROOT_PATH = Path(os.path.abspath(os.getcwd()))
APP_STEAM_APPS_ROOT_PATH = APP_ROOT_PATH / 'steamapps'
APP_STEAM_CMD_DOWNLOADS_ROOT_PATH = APP_ROOT_PATH / 'steamcmd' / 'downloads'
APP_STEAM_CMD_INSTALLED_ROOT_PATH = APP_ROOT_PATH / 'steamcmd'
APP_STEAM_CMD_EXE_FILE_PATH = APP_STEAM_CMD_INSTALLED_ROOT_PATH / 'steamcmd.sh'

class SteamCMD:

    def __init__(self):
        self.download_link = 'https://steamcdn-a.akamaihd.net/client/installer/steamcmd_linux.tar.gz'

    @staticmethod
    def is_numeric(string: str) -> bool:
        return string.isdigit()

    def decompress(self, tar_path: str, decompress_to: str):
        with tarfile.open(tar_path, 'r:gz') as tar_ref:
            tar_ref.extractall(decompress_to)
        print(f"{tar_path} was decompressed successfully!")

    def download_file(self, url: str, save_to: str):
        response = requests.get(url)
        with open(save_to, "wb") as file:
            file.write(response.content)
        print(f"{url} was downloaded successfully!")

    def download_cmd(self):
        d_link_spl = self.download_link.split('/')
        cmp_name = d_link_spl[-1]
        cmp_file_path = APP_STEAM_CMD_DOWNLOADS_ROOT_PATH / cmp_name

        if APP_STEAM_CMD_EXE_FILE_PATH.exists():
            print(f"Skip SteamCMD download, installation found: {APP_STEAM_CMD_EXE_FILE_PATH}")
        else:
            # Create the downloads directory if it does not exist
            APP_STEAM_CMD_DOWNLOADS_ROOT_PATH.mkdir(parents=True, exist_ok=True)

            print('Download latest version of SteamCMD...')
            self.download_file(self.download_link, str(cmp_file_path))
            print(f"Decompress zip to {APP_STEAM_CMD_INSTALLED_ROOT_PATH}...")
            self.decompress(str(cmp_file_path), str(APP_STEAM_CMD_INSTALLED_ROOT_PATH))


    def parse_stdout(self, stdout: str) -> Dict[str, Any]:
        result = ''
        parsed_data: Dict[str, Any] = {}
        inside_vdf = False

        try:
            for line in stdout.split('\n'):
                if line.startswith('"'):
                    inside_vdf = True

                if line.startswith('}'):
                    inside_vdf = False
                    result += '}'

                if inside_vdf:
                    result += f"{line}\n"
                elif len(result) > 0:
                    parsed_data = {**parsed_data, **vdf.loads(result)}
                    result = ''

        except Exception as e:
            print(f"在解析输出数据时出现异常: {e}")
            parsed_data = {}  # 如果有必要，您可以设置一个默认值或返回空字典

        return parsed_data if len(parsed_data) > 0 else stdout

    
    @staticmethod
    def acf_generator(app_id: int, steam_cmd_data: Dict[str, Any]) -> str:
        data = steam_cmd_data[str(app_id)]
        app_name = data["common"]["name"]
        app_install_directory = data["config"]["installdir"]
        app_build_id = data["depots"]["branches"]["public"]["buildid"]
        app_installed_depots: Dict[str, Dict[str, Any]] = {}
        app_shared_depots: Dict[str, str] = {}
        app_size = 0

        app_data_depots = data["depots"]
        for depot_id in app_data_depots:
            if depot_id.isdigit():
                depot_data = app_data_depots[depot_id]
                depot_name = depot_data.get("name")
                depot_size = depot_data.get("maxsize", 0)
                depot_manifest_id = depot_data.get("manifests", {}).get("public")
                depot_os = depot_data.get("config", {}).get("oslist")
                depot_is_dlc = depot_data.get("dlcappid")
                depot_is_shared_install = depot_data.get("sharedinstall")

                if depot_os is None or depot_os == "windows":
                    if depot_is_shared_install is not None:
                        app_shared_depots[depot_id] = depot_data.get("depotfromapp")
                    elif depot_manifest_id is None:
                        print(f"{depot_id} is an unused depot.")
                    else:
                        if app_size == 0:
                            app_size = depot_size

                        app_installed_depots[depot_id] = {
                            "manifest": depot_manifest_id,
                            "size": depot_size,
                        }
                        if depot_is_dlc is not None:
                            app_installed_depots[depot_id]["dlcappid"] = depot_is_dlc
                else:
                    print(f"{depot_id} is not a valid depot for Windows OS.")
            else:
                print(f"{depot_id} SKIP...")

        app_manifest_output = {
            "AppState": {
                "appid": app_id,
                "Universe": 1,
                "LauncherPath": "",
                "name": app_name,
                "StateFlags": 6,
                "installdir": app_install_directory,
                "LastUpdated": 0,
                "SizeOnDisk": app_size,
                "StagingSize": 0,
                "buildid": app_build_id,
                "LastOwner": 2009,
                "UpdateResult": 0,
                "BytesToDownload": 0,
                "BytesDownloaded": 0,
                "BytesToStage": 0,
                "BytesStaged": 0,
                "TargetBuildID": 0,
                "AutoUpdateBehavior": 0,
                "AllowOtherDownloadsWhileRunning": 0,
                "ScheduledAutoUpdate": 0,
            }
        }

        if len(app_installed_depots) > 0:
            app_manifest_output["AppState"]["InstalledDepots"] = app_installed_depots

        if len(app_shared_depots) > 0:
            app_manifest_output["AppState"]["SharedDepots"] = app_shared_depots

        return vdf.dumps(app_manifest_output, pretty=True)

    def exec_raw(self, commands: List[str]) -> subprocess.CompletedProcess:
        return subprocess.run(
            [str(APP_STEAM_CMD_EXE_FILE_PATH), '@ShutdownOnFailedCommand', '1', '@NoPromptForPassword', '1', '+login',
             'anonymous', *commands, '+quit'],
            cwd=str(APP_STEAM_CMD_INSTALLED_ROOT_PATH),
            encoding='utf8',
            errors='replace',
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE
        )

    def apps_info(self, app_ids: List[str]):
        if len(app_ids) > 0:
            print('!DO NOT PANIC IF IT LOOKS STUCK!')

            app_info_print = []
            for app_id in app_ids:
                if self.is_numeric(app_id):
                    app_info_print.extend(['+app_info_print', app_id])
                else:
                    raise ValueError(f"The appId \"{app_id}\" is invalid!")

            # DOWNLOAD CMD
            self.download_cmd()

            # CLEANUP
            print('Remove junk and cache from SteamCMD...')
            app_cache_dir = APP_STEAM_CMD_INSTALLED_ROOT_PATH / 'appcache'
            if app_cache_dir.exists():
                shutil.rmtree(app_cache_dir)

            # Run preCommand to prevent issues with SteamCMD
            print('Running preCommand to prevent issues with SteamCMD...')
            pre_command = app_info_print + ['+force_install_dir', './4', '+app_update', '4']
            self.exec_raw(pre_command)

            # Trying to get data of app_ids
            print(f"Trying to get data of \"{', '.join(app_ids)}\"...")
            command = ['+app_info_update', '1'] + app_info_print
            data = self.exec_raw(command)

            output_app_ids_data = self.parse_stdout(data.stdout)
            if isinstance(output_app_ids_data, dict):
                for output_app_id in output_app_ids_data:
                    manifest = APP_ROOT_PATH / f"appmanifest_{output_app_id}.acf"
                    output = SteamCMD.acf_generator(int(output_app_id), output_app_ids_data)
                    APP_STEAM_APPS_ROOT_PATH.mkdir(parents=True, exist_ok=True)  # 添加这一行代码
                    with open(manifest, "w") as file:
                        file.write(output)
                    print(f"{manifest} was written successfully!")
            else:
                print('Unknown error from SteamCMD:')
                print(output_app_ids_data)
        else:
            print('You have not entered any appId!')

    def app_info(self, app_id: str):
        try:
            self.apps_info([app_id])
        except Exception as e:
            print(f"获取游戏ID {app_id} 的数据时出现错误: {e}")
            
def check_remaining_count(github):
    rate_limit = github.get_rate_limit()
    remaining = rate_limit.core.remaining
    reset_time = rate_limit.core.reset
    reset_time_timestamp = reset_time.timestamp()
    reset_time_datetime = datetime.fromtimestamp(reset_time_timestamp)

    if remaining <= 1:
        wait_time = reset_time_datetime - datetime.now()
        wait_seconds = wait_time.total_seconds()
        print(f"暂停程序 {wait_seconds} 秒,直到 {reset_time_datetime}。现在时间是{datetime.now()}")
        time.sleep(wait_seconds + 10)
    else:
        print(f"剩余请求次数: {remaining}")
        print(f"限制将在 {reset_time_datetime} 重置,现在时间是{datetime.now()}")

def get_all_numeric_branches(github, repo_name):
    check_remaining_count(github)
    repo = github.get_repo(repo_name)
    numeric_branches = []
    all_branches = repo.get_branches()
    for branch in all_branches:
        if branch.name.isdigit() and int(branch.name) > 0:
            numeric_branches.append(branch.name)

    return numeric_branches

def upload_acf_to_repo(github, repo_name, branch, acf_file_name):
    check_remaining_count(github)
    repo = github.get_repo(repo_name)
    with open(acf_file_name, 'rb') as file:
        content = file.read()

    file_exists = False
    try:
        check_remaining_count(github)
        file_obj = repo.get_contents(acf_file_name, ref=branch)
        file_exists = True
    except:
        pass

    if not file_exists or (file_exists and file_obj.decoded_content != content):
        commit_message = f"Update {acf_file_name}"
        if file_exists:
            check_remaining_count(github)
            repo.update_file(acf_file_name, commit_message, content, file_obj.sha, branch=branch)
        else:
            check_remaining_count(github)
            repo.create_file(acf_file_name, commit_message, content, branch=branch)
        print(f"{acf_file_name} has been uploaded to branch {branch}.")
    else:
        print(f"{acf_file_name} has not changed, skipping upload.")
        
def execute_github_operations(github, repo_name, app_id, numeric_branches):
    if app_id in numeric_branches:
        acf_file_name = f"appmanifest_{app_id}.acf"
        if os.path.exists(acf_file_name):
            upload_acf_to_repo(github, repo_name, app_id, acf_file_name)
        else:
            print(f"文件 {acf_file_name} 不存在，跳过上传.")
    else:
        print(f"应用ID {app_id} 的分支不存在。")


if __name__ == "__main__":
    GITHUB_TOKEN = os.environ["KEY"] 
    REPO_NAME = "xxTree/ManifestAutoUpdate"  
    steamcmd = SteamCMD()
    github = Github(GITHUB_TOKEN)
    check_remaining_count(github)
    numeric_branches = get_all_numeric_branches(github, REPO_NAME)

    for branch in numeric_branches:
        app_id = branch
        steamcmd.app_info(app_id)

        execute_github_operations(github, REPO_NAME, app_id, numeric_branches)
