cask "netaudit" do
  version "0.9.7"
  sha256 "a22a471366b8acea4d8141f0f865d0422cc54df69e8b0accf9e31130f6af077e"

  url "https://github.com/sreebalakrishnan/netaudit/releases/download/v#{version}/NetAudit-#{version}.dmg"
  name "NetAudit"
  desc "Native macOS network audit — Wi-Fi safety check + LAN device classifier"
  homepage "https://github.com/sreebalakrishnan/netaudit"

  livecheck do
    url :url
    strategy :extract_plist
  end

  app "NetAudit.app"
  # `netaudit` terminal command → a shim script inside the app (a direct symlink
  # to the py2app executable can't find the bundle; the shim execs it by real path).
  binary "#{appdir}/NetAudit.app/Contents/Resources/netaudit", target: "netaudit"

  # NetAudit ships ad-hoc signed (no paid Apple Developer Program). Strip the
  # quarantine attribute so Gatekeeper stays silent on first launch — this is
  # the same thing INSTALL.md asks users to do by hand.
  postflight do
    system_command "/usr/bin/xattr",
                   args: ["-cr", "#{appdir}/NetAudit.app"],
                   sudo: false
  end

  zap trash: [
    "~/.netaudit",
  ]
end
