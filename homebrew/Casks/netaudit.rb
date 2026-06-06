cask "netaudit" do
  version "0.9.6"
  sha256 "9078ac72167f9ba5658c610ef6e5ea935ce117ea300bc29ef27a10a3f6de167e"

  url "https://github.com/sreebalakrishnan/netaudit/releases/download/v#{version}/NetAudit-#{version}.dmg"
  name "NetAudit"
  desc "Native macOS network audit — Wi-Fi safety check + LAN device classifier"
  homepage "https://github.com/sreebalakrishnan/netaudit"

  livecheck do
    url :url
    strategy :extract_plist
  end

  app "NetAudit.app"
  # `netaudit` terminal command → the app's executable (CLI verdict when run from
  # a shell; `netaudit gui` opens the menu-bar app).
  binary "#{appdir}/NetAudit.app/Contents/MacOS/NetAudit", target: "netaudit"

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
