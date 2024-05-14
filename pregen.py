import os
import re
import sys
import math
import time
import json
import shutil
import nbtlib
import pathlib
import requests
import subprocess

cache_dir_path = "cache"
versions_dir_path = os.path.join(cache_dir_path, "versions")
server_dir_path = "server"
server_properties_path = os.path.join(server_dir_path, "server.properties")
world_dir_path = os.path.join(server_dir_path, "world")
level_dat_path = os.path.join(world_dir_path, "level.dat")

def setup_dirs():
    pathlib.Path(server_dir_path).mkdir(exist_ok = True)
    pathlib.Path(cache_dir_path).mkdir(exist_ok = True)
    pathlib.Path(versions_dir_path).mkdir(exist_ok = True)

def make_cached(func):
    cache = {}
    def decorated(*args):
        key = tuple(*args)
        if key in cache:
            return cache[key]
        return func(*args)
    return decorated

def get_cached_json(cached_path: str, getter):
    try:
        with open(cached_path) as f:
            return json.load(f)
    except:
        data = getter()
        with open(cached_path, "w") as f:
            json.dump(data, f)
        return data

def download_version_manifest():
    print("Getting official version manifest")
    return requests.get("https://piston-meta.mojang.com/mc/game/version_manifest_v2.json").json()

@make_cached
def get_version_manifest():
    cached_path = os.path.join(cache_dir_path, "version_manifest_v2.json")
    return get_cached_json(cached_path, download_version_manifest)

@make_cached
def get_official_version_json_urls():
    version_json_urls = {}
    version_manifest = get_version_manifest()
    for version in version_manifest["versions"]:
        id = version["id"]
        url = version["url"]
        if id in version_json_urls:
            print(f"Duplicate version id: {id} {version_json_urls[id]} {url}")
        version_json_urls[version["id"]] = url
    return version_json_urls

@make_cached
def get_official_version_server_url(version: str) -> str:
    version_json_urls = get_official_version_json_urls()
    if version not in version_json_urls:
        return None
    
    version_json_url = version_json_urls[version]
    print(f"Getting version json for {version}")
    version_json = requests.get(version_json_url).json()

    downloads = version_json["downloads"]
    if "server" not in downloads:
        return None

    return downloads["server"]["url"]

def download_archived_versions() -> "dict[str, str]":
    print("Getting a list of archived versions")
    base_url = "https://files.betacraft.uk/server-archive/"
    archived_versions = {}
    def walk(url: str):
        html = requests.get(url).text
        for m in re.finditer("<a href=\"([^\"]+)\">([^<]+)</a>", html):
            relative_url = m.group(1)
            if relative_url == "../":
                continue
            name = m.group(2)

            new_url = url + relative_url
            if relative_url.endswith("/"):
                walk(new_url)
            elif name.endswith(".jar"):
                name = name[:-4]
                if name in archived_versions:
                    print(f"Duplicate version name: {name} {archived_versions[name]} {new_url}")
                archived_versions[name] = new_url
    walk(base_url)
    return archived_versions

@make_cached
def get_archived_versions() -> "dict[str, str]":
    cached_path = os.path.join(cache_dir_path, "archived_versions.json")
    return get_cached_json(cached_path, download_archived_versions)

def get_archived_version_server_url(version: str) -> str:
    archived_versions = get_archived_versions()

    if version not in archived_versions:
        return None
    
    return archived_versions[version]

def get_version_server_jar_path(version: str) -> str:
    path = os.path.join(versions_dir_path, f"{version}.jar")
    if os.path.isfile(path):
        return path
    
    url = get_official_version_server_url(version)
    if url is None:
        url = get_archived_version_server_url(version)

    if url is not None:
        print(f"Downloading server jar for {version} from {url}")
        with requests.get(url) as r:
            r.raise_for_status()
            with open(path, "wb") as f:
                for chunk in r.iter_content(chunk_size=8192):
                    f.write(chunk)
        return path

    return None

def print_usage():
    print("Usage:")
    print(f"python {sys.argv[0]} clean    Delete almost everything in the server directory")
    print(f"python {sys.argv[0]} run <version>    Run the specifient version once, used to upgrade the world format")
    print(f"python {sys.argv[0]} pregen <version> [--seed <seed>] <spawn_x> <spawn_z> <chunk_radius>    Generate at least the specified area with the specified version[ and seed]")

def delete_dir_contents(path: str, exceptions: "set[str]"):
    for filename in os.listdir(path):
        if filename in exceptions:
            continue
        file_path = os.path.join(path, filename)
        try:
            if os.path.isfile(file_path) or os.path.islink(file_path):
                os.unlink(file_path)
            elif os.path.isdir(file_path):
                shutil.rmtree(file_path)
        except Exception as e:
            print(f"Failed to delete {file_path}. Reason: {e}")

def clean():
    print(f"Deleting contents of {server_dir_path}")
    delete_dir_contents(server_dir_path, {"eula.txt", "world"})
    delete_dir_contents(world_dir_path, set())

def run_server(server_jar_path: str, print_stdout = False):
    print(f"Running {server_jar_path}")
    start = time.time()
    try:
        process = subprocess.run(["java", "-jar", os.path.abspath(server_jar_path), "nogui"], cwd = server_dir_path, input = b"stop\n", stdout = subprocess.PIPE, stderr = subprocess.STDOUT, check = True)
        stdout = process.stdout.decode(errors="replace")
        no_success_message = 'For help, type "help"' not in stdout
        if print_stdout or no_success_message:
            print(stdout)
        if no_success_message:
            raise RuntimeError("The server didn't run successfully")
        # error_messages = {
        #     "You need to agree to the EULA in order to run the server": None,
        #     "This world must be opened in an older version (like 1.6.4) to be safely converted": None,
        #     "[SEVERE] Unexpected exception": "[SEVERE] Unexpected exception (Seems to just happen randomly on old alpha versions, try again I guess)",
        # }
        # for (k, v) in error_messages.items():
        #     if v is None:
        #         v = k
        #     if k in stdout:
        #         if not print_stdout:
        #             print(stdout)
        #         raise RuntimeError(v)
    finally:
        end = time.time()
        print(f"Took {end - start} s")

def run(server_jar_path: str):
    run_server(server_jar_path)
    pass

def level_dat_get_seed(level_dat_path: str) -> int:
    with nbtlib.load(level_dat_path) as level_dat:
        Data = level_dat[""]["Data"]
        if "RandomSeed" in Data:
            return int(Data["RandomSeed"])
        return Data["WorldGenSettings"]["seed"]

def level_dat_set_seed(level_dat_path: str, seed: int):
    with nbtlib.load(level_dat_path) as level_dat:
        Data = level_dat[""]["Data"]
        if "RandomSeed" in Data:
            Data["RandomSeed"] = nbtlib.tag.Long(seed)
        else:
            raise RuntimeError("Can't set seed through level.dat for new versions")

def level_dat_get_spawn_pos(level_dat_path: str) -> "tuple[int, int]":
    with nbtlib.load(level_dat_path) as level_dat:
        Data = level_dat[""]["Data"]
        return (int(Data["SpawnX"]), int(Data["SpawnZ"]))

def level_dat_set_spawn_pos(level_dat_path: str, spawn_x: int, spawn_z: int):
    with nbtlib.load(level_dat_path) as level_dat:
        Data = level_dat[""]["Data"]
        Data["SpawnX"] = nbtlib.tag.Int(spawn_x)
        Data["SpawnZ"] = nbtlib.tag.Int(spawn_z)

def pregen(server_jar_path: str, seed: "int | None", spawn_x: int, spawn_z: int, chunk_radius: int):
    print(f"pregen {server_jar_path} {seed} {spawn_x} {spawn_z} {chunk_radius}")
    
    final_spawn_x = 0
    final_spawn_z = 0

    if seed is not None:
        if os.path.isfile(level_dat_path):
            current_seed = level_dat_get_seed(level_dat_path)
            if current_seed != seed:
                print(f"Current world uses a different seed ({current_seed} != {seed}), delete it first")
                return
            else:
                print("Existing world uses the same seed, keeping it")
                (final_spawn_x, final_spawn_z) = level_dat_get_spawn_pos(level_dat_path)
        else:
            print("No existing level.dat found")
            clean()
            print("Trying to set the seed through server.properties")
            with open(server_properties_path, "w") as f:
                f.write(f"level-seed={seed}")
            run_server(server_jar_path)
            if level_dat_get_seed(level_dat_path) == seed:
                print("Successfully set the seed through server.properties")
                (final_spawn_x, final_spawn_z) = level_dat_get_spawn_pos(level_dat_path)
                # print("Deleting world data generated with the correct seed anyway")
                # delete_dir_contents(world_dir_path, {"level.dat"})
            else:
                print("Could not set the seed through server.properties, modifying level.dat")
                level_dat_set_seed(level_dat_path, seed)
                print("Deleting world data generated with the random seed")
                delete_dir_contents(world_dir_path, {"level.dat"})
    
    # spawn 8 8
    # a0.1.0 - -10..=10 gets generated, -10..=9 gets populated
    # a0.2.0 - -10..=10 gets generated, -10..=9 gets populated
    # b1.8.1 - -12..=12 gets generated, -12..=11 gets populated
    # 1.0.0 - -12..=12 gets generated, -12..=11 gets populated
    # 1.12.2 - -12..=12 gets generated, -12..=11 gets populated
    # 1.13.2 - -13..=13 gets decorated, -12..=12 gets fullchunk
    # 1.14.4 - -11..=11 gets full
    # 1.16.5 - -11..=11 gets full
    # 1.19.3 - -12..=12 gets features, -11..=11 gets full
    spawn_chunk_diameter = 19 # should be enough for all versions

    step_radius = max(math.ceil((chunk_radius + 1) / spawn_chunk_diameter - 0.5), 0)

    rounded_spawn_x = (spawn_x >> 4 << 4) + 8
    rounded_spawn_z = (spawn_z >> 4 << 4) + 8

    i = 0
    total_steps = (step_radius * 2 + 1) ** 2
    for dx in range(-step_radius, step_radius+1):
        for dz in range(-step_radius, step_radius+1):
            offset_spawn_x = rounded_spawn_x + dx * spawn_chunk_diameter * 16
            offset_spawn_z = rounded_spawn_z + dz * spawn_chunk_diameter * 16
            print(f"Setting spawn pos to {offset_spawn_x} {offset_spawn_z}")
            level_dat_set_spawn_pos(level_dat_path, offset_spawn_x, offset_spawn_z)
            run_server(server_jar_path)
            i += 1
            print(f"{i} / {total_steps} | {100 * i / total_steps:.1f}% Done")
    
    level_dat_set_spawn_pos(level_dat_path, final_spawn_x, final_spawn_z)


def abort(*args):
    print(*args)
    exit(1)

def main():
    setup_dirs()

    i = 1
    argv = sys.argv
    if i >= len(argv):
        print_usage()
        return
    
    def peek_next_argument(expected):
        nonlocal i
        if i >= len(argv):
            abort(f"Not enough arguments, expected {expected}")
        return argv[i]
    
    def get_next_argument(expected):
        nonlocal i
        val = peek_next_argument(expected)
        i += 1
        return val
    
    def end_arguemnts():
        nonlocal i
        if i < len(argv):
            abort(f"Ignored arguments: {argv[i:]}")

    cmd = get_next_argument("clean | run | pregen")

    if cmd == "clean":
        end_arguemnts()
        clean()
    elif cmd == "run":
        version = get_next_argument("<version>")

        end_arguemnts()

        server_jar_path = get_version_server_jar_path(version)
        if server_jar_path is None:
            abort(f"Could not find server jar for version: {version}")

        run(server_jar_path)
    elif cmd == "pregen":
        version = get_next_argument("<version>")
        
        seed = None
        if peek_next_argument("--seed | <version>") == "--seed":
            get_next_argument("--seed | <version>")
            seed = int(get_next_argument("<seed>"))

        spawn_x = int(get_next_argument("<spawn_x>"))
        spawn_z = int(get_next_argument("<spawn_z>"))
        chunk_radius = int(get_next_argument("<chunk_radius>"))

        end_arguemnts()

        server_jar_path = get_version_server_jar_path(version)
        if server_jar_path is None:
            abort(f"Could not find server jar for version: {version}")

        pregen(server_jar_path, seed, spawn_x, spawn_z, chunk_radius)
    else:
        abort(f"Unknown subcommand: {cmd}")

if __name__ == "__main__":
    main()