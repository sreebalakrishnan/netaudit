# Publishing NetAudit via Homebrew

Goal: let people install with one line.

```bash
brew install sreebalakrishnan/netaudit/netaudit
```

## Why a custom tap, not main `homebrew-cask`

The official [`homebrew-cask`](https://github.com/Homebrew/homebrew-cask) repo requires apps to be:

- Code signed with a Developer ID (we're ad-hoc only — no paid Apple cert)
- Notarized via Apple's notary service
- Maintained and have a user base

NetAudit doesn't clear that bar yet. The clean workaround is a **personal Homebrew tap** — your own `homebrew-*` GitHub repo that anyone can use without joining the main cask repo.

When you eventually get a Developer ID + notarize, the same cask formula will work in main `homebrew-cask` with minor edits.

## One-time setup: create the tap repo

A Homebrew tap is just a public GitHub repo named `homebrew-<anything>` containing `Casks/*.rb` files.

```bash
# 1. Create a fresh repo on GitHub (public).
gh repo create sreebalakrishnan/homebrew-netaudit --public --description "Homebrew tap for NetAudit"

# 2. Clone it locally somewhere.
cd /Users/sreeb/Developer
gh repo clone sreebalakrishnan/homebrew-netaudit
cd homebrew-netaudit

# 3. Copy the cask formula in from this repo.
mkdir -p Casks
cp /Users/sreeb/Developer/netaudit/homebrew/Casks/netaudit.rb Casks/

# 4. Add a tiny README.
cat > README.md <<'EOF'
# homebrew-netaudit

Homebrew tap for [NetAudit](https://github.com/sreebalakrishnan/netaudit) — a native macOS network audit + Wi-Fi safety checker.

## Install

```bash
brew install sreebalakrishnan/netaudit/netaudit
```

## Update

```bash
brew upgrade --cask netaudit
```

## Uninstall

```bash
brew uninstall --cask netaudit
brew untap sreebalakrishnan/netaudit
```
EOF

# 5. Commit and push.
git add . && git commit -m "Initial tap with NetAudit cask"
git push
```

That's it. Anyone can now `brew install sreebalakrishnan/netaudit/netaudit`.

## Per-release flow

```bash
# 1. Bump the version in setup.py (CFBundleVersion + CFBundleShortVersionString),
#    then rebuild bundle + DMG + auto-update the cask formula.
cd /Users/sreeb/Developer/netaudit
./build.sh                 # writes homebrew/Casks/netaudit.rb with new version + sha256

# 2. Cut a GitHub Release with the DMG attached under BOTH names: the versioned
#    one (cask, sha-pinned) and a stable NetAudit.dmg (install.sh latest URL).
cp NetAudit-X.Y.Z.dmg NetAudit.dmg
gh release create vX.Y.Z NetAudit-X.Y.Z.dmg NetAudit.dmg --title "NetAudit vX.Y.Z" --notes "…"
rm NetAudit.dmg

# 3. Copy the updated cask formula into the tap repo, commit, push.
#    (The cask must NOT have a `verified:` param — brew audit rejects it now that
#     the url + homepage domains both = github.com.)
cp homebrew/Casks/netaudit.rb /Users/sreeb/Developer/homebrew-netaudit/Casks/
cd /Users/sreeb/Developer/homebrew-netaudit
git commit -am "netaudit X.Y.Z" && git push

# 4. Brew users get the update on `brew upgrade --cask netaudit`.
```

## Testing the formula locally before pushing

```bash
# Audit (lint) the cask
brew tap sreebalakrishnan/netaudit
brew audit --cask --strict --token-conflicts netaudit

# Install from your local tap
brew install --cask sreebalakrishnan/netaudit/netaudit

# When done testing
brew uninstall --cask netaudit
brew untap sreebalakrishnan/netaudit
```

## What `postflight` does

The cask runs `xattr -cr` on the installed `NetAudit.app`, stripping `com.apple.quarantine`. This is the *same thing* `install.sh` does — Homebrew users get a silent first launch with no Gatekeeper warning, the same way the `curl … | bash` users do.

If/when NetAudit is properly notarized, you can delete the `postflight` block — the quarantine attribute is harmless on signed-and-notarized apps because Gatekeeper recognizes the signature.

## Future: getting into main `homebrew-cask`

Once you have a Developer ID + notarization:

1. Edit `Casks/netaudit.rb` to remove the `postflight` block (no longer needed).
2. Submit a PR to [`Homebrew/homebrew-cask`](https://github.com/Homebrew/homebrew-cask) following their [contribution guide](https://docs.brew.sh/Cask-Cookbook).
3. After merge, users install with just `brew install --cask netaudit` (no tap prefix).
