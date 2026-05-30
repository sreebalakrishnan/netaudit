cask "netaudit" do
  version "0.8.0"
  sha256 "1bd3daf3f13b09ad6f7839dd823af52cce94f3d3973edeae69f23a3db7585833"

  url "https://netaudit.sreeb.dev/NetAudit-#{version}.dmg"
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
