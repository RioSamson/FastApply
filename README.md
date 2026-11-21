# FastApply

FastApply imports job links and fills application drafts in Safari. You review and submit each application yourself.

## Setup

Requires macOS, Safari, and Python 3.10 or newer.

1. In Safari, enable **Settings → Advanced → Show features for web developers**, then **Develop → Allow JavaScript from Apple Events**.
2. Run `./Launch.command`. If macOS prompts for Automation access, allow Terminal to control Safari.
3. Open **Edit profile**, add the fields you want filled, and set `resume_path` to the absolute path of your PDF or DOCX. Paste a job email, then click **Preview jobs** and **Start batch**.

FastApply creates `private/` on first launch. It stores your profile, learned answers, job history, and cached documents there. Keep that folder local.

AI review uses the Codex CLI if it is installed and signed in. FastApply sends field checks without sending your answers or résumé.

## Tests

Run `python3 -m unittest test_core`. To try the browser workflow with local sample forms, run `./Launch.command --fixtures --port 8875 --data-dir "$(mktemp -d)"` and click **Test fixtures**.

The early commit history was reconstructed from saved versions. Author dates reflect those snapshots.
