"""Network-share safety tests. Never mount a real share or edit the host fstab."""

import unittest
import re
from pathlib import Path

from test_workflows import run_bash


class NetworkShareTests(unittest.TestCase):
    def check_run(self, body, stdin=""):
        result = run_bash(body, stdin)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        return result.stdout + result.stderr

    def test_share_intro_explains_what_poedeploy_will_do(self):
        output = self.check_run('setup_smb_share')
        self.assertIn('SMB share setup', output)
        self.assertIn('PoeDeploy will save this share for future use only after confirming', output)
        self.assertNotIn('test first', output)

    def test_script_and_documentation_avoid_unwanted_punctuation(self):
        root = Path(__file__).resolve().parents[1]
        paths = [root / 'poedeploy.sh', *root.glob('*.md'), *root.glob('docs/**/*.md'),
                 *root.glob('themes/**/*.md')]
        for path in paths:
            with self.subTest(path=path.relative_to(root)):
                self.assertNotIn(chr(0x2014), path.read_text())
                if path.suffix == '.md':
                    self.assertNotIn(';', path.read_text())

    def test_user_facing_script_text_does_not_use_semicolons(self):
        script = Path(__file__).resolve().parents[1] / 'poedeploy.sh'
        for number, line in enumerate(script.read_text().splitlines(), 1):
            stripped = line.strip()
            match = re.match(r'(?:info|success|warning|error|die|echo)\s+"([^"]*)"', stripped)
            if match:
                with self.subTest(line=number):
                    self.assertNotIn(';', match.group(1))

    def test_rejects_unsafe_mountpoints_and_fstab_fields(self):
        self.check_run(r'''
for path in / /boot /etc /home /mnt /media /mnt/../boot /mnt//NAS /mnt/NAS/ '/mnt/a b' '/mnt/a#b' '/mnt/a,b' '/mnt/a\040b'; do
    if validate_mountpoint "$path"; then echo "Accepted unsafe path: $path"; exit 91; fi
done
validate_mountpoint /mnt/poedeploy-test-nas
validate_mountpoint /media/poedeploy-test-nas
for value in '' 'a b' 'a#b' 'a,b' 'a\040b' $'a\nb'; do
    if validate_fstab_value test "$value"; then exit 92; fi
done
''')

    def test_rejects_urls_invalid_sources_and_relative_exports(self):
        self.check_run(r'''
if validate_share_source SMB https://nas/data data; then exit 91; fi
if validate_share_source SMB nas data/subdir; then exit 92; fi
if validate_share_source NFS nas exports/data; then exit 93; fi
if validate_share_source NFS '-o' /data; then exit 94; fi
validate_share_source NFS '[2001:db8::1]' /data
validate_share_source SMB nas.local data
''')

    def test_symlink_mountpoint_is_rejected(self):
        self.check_run(r'''
realpath() { printf '/boot\n'; }
if validate_mountpoint /mnt/link-to-boot; then exit 91; fi
''')

    def test_nonempty_mount_directory_is_not_hidden(self):
        self.check_run(r'''
task_dir=$(mktemp -d)
trap 'rm -rf -- "$task_dir"' EXIT
printf 'keep this file\n' > "$task_dir/local-file"
fstab_has_mountpoint() { return 1; }
share_mount_record() { return 1; }
sudo() {
    [[ "$1" == find && "$2" == "$task_dir" ]] || exit 97
    command "$@"
}
if try_network_share NFS nas:/data "$task_dir"; then exit 91; fi
[[ $(< "$task_dir/local-file") == 'keep this file' ]]
''')

    def test_retry_then_success_for_both_protocols(self):
        for kind, remote in (("SMB", "data"), ("NFS", "/data")):
            with self.subTest(kind=kind):
                details = f"nas\n{remote}\n/mnt/poedeploy-test-nas\n"
                if kind == "SMB":
                    details += "alice\npassword\n\n"
                output = self.check_run(f'kind={kind}\n' + r'''
attempts=0
try_network_share() {
    attempts=$((attempts + 1))
    ((attempts == 2))
}
setup_network_share "$kind"
[[ $attempts == 2 ]]
declare -n result="${kind}_ACTION"
[[ "$result" == 'configured and mount verified' ]]
''', details + "r\n" + details)
                self.assertNotIn("password", output)

    def test_failed_setup_skips_by_default_for_both_protocols(self):
        for kind, remote in (("SMB", "data"), ("NFS", "/data")):
            with self.subTest(kind=kind):
                details = f"nas\n{remote}\n/mnt/poedeploy-test-nas\n"
                if kind == "SMB":
                    details += "alice\npassword\n\n"
                self.check_run(f'kind={kind}\n' + r'''
try_network_share() { return 1; }
setup_network_share "$kind"
declare -n result="${kind}_ACTION"
[[ "$result" == 'skipped after failed attempt' ]]
''', details + "\n")

    def test_eof_cancels_without_setup(self):
        self.check_run(r'''
try_network_share() { exit 91; }
setup_smb_share
setup_nfs_share
[[ "$SMB_ACTION" == cancelled && "$NFS_ACTION" == cancelled ]]
''')

    def test_skipping_smb_does_not_skip_selected_nfs(self):
        self.check_run(r'''
ensure_command_dependencies() { :; }
setup_smb_share() { SMB_ACTION='skipped after failed attempt'; }
setup_nfs_share() { NFS_ACTION='configured and mount verified'; }
configure_network_shares
[[ "$SMB_ACTION" == 'skipped after failed attempt' ]]
[[ "$NFS_ACTION" == 'configured and mount verified' ]]
''', "3\n")

    def test_cleanup_failure_stops_instead_of_offering_retry(self):
        result = run_bash(r'''
try_network_share() { return 2; }
setup_nfs_share
echo SHOULD_NOT_CONTINUE
''', "nas\n/data\n/mnt/poedeploy-test-nas\nr\n")
        self.assertEqual(result.returncode, 1)
        self.assertNotIn("SHOULD_NOT_CONTINUE", result.stdout)

    def run_attempt(self, kind, scenario):
        return self.check_run(f'kind={kind}\nscenario={scenario}\n' + r'''
task_dir=$(mktemp -d)
trap 'rm -rf -- "$task_dir"' EXIT
mountpoint="$task_dir/mountpoint"
fixture_source='nas:/data'
fixture_type=nfs4
if [[ "$kind" == SMB ]]; then fixture_source='//nas/data'; fixture_type=cifs; fi
fstab_has_mountpoint() { [[ "$scenario" == duplicate || -f "$task_dir/saved" ]]; }
share_mount_record() {
    if [[ "$scenario" == existing ]]; then printf '%s ext4\n' /dev/existing; return 0; fi
    [[ -f "$task_dir/mounted" ]] || return 1
    printf '%s %s\n' "$fixture_source" "$fixture_type"
}
sudo() {
    case "$1" in
        mkdir) return 0 ;;
        mktemp) command mktemp "$task_dir/credentials-XXXXXX" ;;
        tee)
            [[ "$2" == "$task_dir"/credentials-* ]] || exit 97
            [[ $(stat -c %a "$2") == 600 ]] || exit 96
            [[ "$scenario" != credential_fail ]] || return 1
            command tee "$2" ;;
        rm)
            [[ "$*" == "rm -f -- $task_dir/credentials-"* ]] || exit 97
            command "$@" ;;
        timeout)
            [[ "$2 $3" == '--kill-after=5s 30s' ]] || exit 97
            if [[ "$4" == mount ]]; then
                [[ "$5" == --fstab && "$7" == --target && "$8" == "$mountpoint" ]] || exit 97
                [[ ! -f "$task_dir/saved" ]] || exit 95
                cp -- "$6" "$task_dir/trial-copy"
                case "$scenario" in
                    mount_fail) return 32 ;;
                    timeout) return 124 ;;
                    no_mount) return 0 ;;
                esac
                touch "$task_dir/mounted"
                if [[ "$scenario" == signal ]]; then kill -s TERM "$BASHPID"; fi
                return 0
            elif [[ "$4" == umount ]]; then
                [[ "$scenario" != cleanup_fail ]] || return 1
                command rm -- "$task_dir/mounted"
                touch "$task_dir/unmounted"
                return 0
            fi
            exit 97 ;;
        *) echo "UNEXPECTED: $*"; exit 97 ;;
    esac
}
timeout() {
    [[ "$*" == "--kill-after=5s 15s ls -A -- $mountpoint" ]] || exit 97
    [[ "$scenario" != access_fail && "$scenario" != cleanup_fail ]]
}
persist_verified_share() {
    [[ -f "$task_dir/mounted" ]] || exit 95
    [[ "$scenario" != save_fail ]] || return 1
    printf '%s\n' "$1" > "$task_dir/saved"
    [[ "$scenario" != rollback_fail ]] || return 2
}
status=0
try_network_share "$kind" "$fixture_source" "$mountpoint" alice 'secret,with=punctuation' WORKGROUP || status=$?
case "$scenario" in
    success)
        [[ $status == 0 && -f "$task_dir/saved" && -f "$task_dir/mounted" ]]
        grep -q 'nofail,x-systemd.automount,x-systemd.mount-timeout=30s' "$task_dir/saved"
        if [[ "$kind" == SMB ]]; then
            compgen -G "$task_dir/credentials-*" >/dev/null
            if grep -q secret "$task_dir/saved"; then exit 91; fi
        else
            grep -q 'fg,retry=0' "$task_dir/saved"
            if grep -q ',soft' "$task_dir/saved"; then exit 91; fi
        fi ;;
    cleanup_fail)
        [[ $status == 2 && ! -f "$task_dir/saved" && -f "$task_dir/mounted" ]] ;;
    rollback_fail)
        [[ $status == 2 && -f "$task_dir/saved" && -f "$task_dir/mounted" ]]
        if [[ "$kind" == SMB ]]; then compgen -G "$task_dir/credentials-*" >/dev/null; fi ;;
    signal)
        [[ $status == 143 && ! -f "$task_dir/saved" && ! -f "$task_dir/mounted" ]]
        if compgen -G "$task_dir/credentials-*" >/dev/null; then exit 92; fi ;;
    *)
        [[ $status == 1 && ! -f "$task_dir/saved" && ! -f "$task_dir/mounted" ]]
        if compgen -G "$task_dir/credentials-*" >/dev/null; then exit 92; fi ;;
esac
''')

    def test_mount_failures_timeout_and_false_success_never_persist(self):
        for kind in ("SMB", "NFS"):
            for scenario in ("mount_fail", "timeout", "no_mount"):
                with self.subTest(kind=kind, scenario=scenario):
                    self.run_attempt(kind, scenario)

    def test_access_or_save_failure_unmounts_and_removes_new_credentials(self):
        for kind in ("SMB", "NFS"):
            for scenario in ("access_fail", "save_fail"):
                with self.subTest(kind=kind, scenario=scenario):
                    self.run_attempt(kind, scenario)

    def test_success_persists_only_verified_mount(self):
        for kind in ("SMB", "NFS"):
            with self.subTest(kind=kind):
                self.run_attempt(kind, "success")

    def test_existing_entries_and_mounts_are_not_modified(self):
        for kind in ("SMB", "NFS"):
            for scenario in ("duplicate", "existing"):
                with self.subTest(kind=kind, scenario=scenario):
                    self.run_attempt(kind, scenario)

    def test_failed_unmount_requires_manual_attention(self):
        for kind in ("SMB", "NFS"):
            with self.subTest(kind=kind):
                self.run_attempt(kind, "cleanup_fail")

    def test_credentials_still_referenced_after_failed_rollback_are_retained(self):
        for kind in ("SMB", "NFS"):
            with self.subTest(kind=kind):
                self.run_attempt(kind, "rollback_fail")

    def test_interruption_cleans_up_unpersisted_mount_and_credentials(self):
        for kind in ("SMB", "NFS"):
            with self.subTest(kind=kind):
                self.run_attempt(kind, "signal")

    def test_credential_write_failure_leaves_no_new_credential_file(self):
        self.run_attempt("SMB", "credential_fail")

    def test_fstab_transaction_preserves_existing_content_and_rolls_back(self):
        for scenario in ("success", "verify_fail", "reload_fail", "concurrent_edit", "duplicate"):
            with self.subTest(scenario=scenario):
                self.check_run(f'export scenario={scenario}\n' + r'''
export task_dir=$(mktemp -d)
trap 'rm -rf -- "$task_dir"' EXIT
fixture="$task_dir/fstab"
printf '# existing content\nUUID=root / ext4 defaults 0 1\n' > "$fixture"
if [[ "$scenario" == duplicate ]]; then
    printf 'nas:/old /mnt/test nfs nofail 0 0\n' >> "$fixture"
fi
chmod 640 "$fixture"
cp "$fixture" "$task_dir/original"
findmnt() {
    if [[ "$1" == --verify ]]; then [[ "$scenario" != verify_fail ]]; return; fi
    command findmnt "$@"
}
systemctl() {
    [[ "$*" == daemon-reload ]] || exit 97
    if [[ "$scenario" == reload_fail && ! -f "$task_dir/reload-failed" ]]; then
        touch "$task_dir/reload-failed"; return 1
    elif [[ "$scenario" == concurrent_edit ]]; then
        printf '# unrelated concurrent edit\n' >> "$task_dir/fstab"
        return 1
    fi
}
export -f findmnt systemctl
sudo() {
    [[ $# == 6 && "$1 $2 $3" == 'bash -s --' && "$6" == "$task_dir/fstab" ]] || exit 97
    command "$@"
}
status=0
persist_verified_share 'nas:/data /mnt/test nfs nofail 0 0' /mnt/test "$fixture" || status=$?
case "$scenario" in
    success)
        [[ $status == 0 && $(stat -c %a "$fixture") == 640 ]]
        grep -Fq 'UUID=root / ext4 defaults 0 1' "$fixture"
        grep -Fq 'nas:/data /mnt/test nfs nofail 0 0' "$fixture"
        compgen -G "$fixture.poedeploy-backup.*" >/dev/null ;;
    concurrent_edit)
        [[ $status == 2 ]]
        grep -q 'unrelated concurrent edit' "$fixture" ;;
    *) [[ $status != 0 ]]; cmp "$fixture" "$task_dir/original" ;;
esac
if compgen -G "$fixture.poedeploy-new.*" >/dev/null; then exit 91; fi
if compgen -G "$fixture.poedeploy-expected.*" >/dev/null; then exit 92; fi
''')
