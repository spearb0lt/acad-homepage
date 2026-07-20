# Local preview of the site via Docker (Jekyll / GitHub Pages).
# Usage:  right-click > Run with PowerShell,  or  .\serve.ps1
# Then open http://localhost:4000  (Ctrl+C to stop)

docker run --rm -it `
  -v "${PWD}:/srv/jekyll" `
  -v "acad_bundle:/usr/local/bundle" `
  -p 4000:4000 `
  jekyll/jekyll:pages `
  sh -c "bundle install && bundle exec jekyll serve --host 0.0.0.0 --force_polling --livereload"
