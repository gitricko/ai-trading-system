# Serve the repo root so the dashboard lives at /dashboard/
# and any results/ asset can be fetched at its repo-relative path.

start:
	python3 -m http.server 8778
