---
name: add-a-page
description: Add or change something on the public website in apps/website/. Interviews the user briefly about content and placement, implements it matching the existing site, pushes, and tells them when to refresh. Use for any website change request: a new page, edited text, photos, a list, a menu item, "put something on the site".
---

# Add a page

The user is not a developer. Interview first, build second.

## 1. Interview, briefly

One question at a time, plain words:

- What should the page or feature be? (new page, change to an existing page, photos, text, a list, a form?)
- Who is it for, and should it be linked from the homepage or the menu?
- Do they have content ready (text, photos)? If photos, name the repo folder to drop the files into, and wait for them.
- Any look-and-feel wishes? If they say "you pick", pick something clean that matches the existing site.

Play the plan back in three or four plain sentences and get a yes before touching files.

## 2. Build

- Implement in `apps/website/`, matching the existing style and structure. Keep it simple: no new frameworks, no build tools that are not already there. Optimise images to sensible sizes.
- Check the work locally as far as possible: valid HTML, links resolve, images load from their referenced paths.

## 3. Ship

- Commit with a clear message and push to main. Explain in one sentence: the server tests and deploys it within a few minutes.
- Tell them exactly when and where to look: which URL to open, and to refresh after a few minutes. If it does not show, read the server's statuses on the commit page (`gh api repos/<repo>/commits/<sha>/statuses`) before guessing.
- End with a plain-words summary: what changed, which files, and the URL where they can see it.
