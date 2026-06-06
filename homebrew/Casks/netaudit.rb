cask "netaudit" do
  version "0.9.4"
  sha256 "f05e0046c69541ad44db6ce415fb74fa104dc4c5dd9deaf2b10da1a2b86fb1f2"

  url "https://github.com/sreebalakrishnan/netaudit/releases/download/v#{version}/NetAudit-#{version}.dmg"
  name "NetAudit"
  desc "Native macOS network audit — Wi-Fi safety check + LAN device classifier"
  homepage "https://github.com/sreebalakrishnan/netaudit"

  livecheck do
    url :url
    strategy :extract_plist
  end

  app "NetAudit.app"

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
