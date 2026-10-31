# The public website: a stock nginx image with the static files copied in.
# Build context is the repository root (apps/website/compose.yml sets it), so
# the COPY paths are relative to the repository, not to this Dockerfile.
FROM nginx:alpine

COPY apps/website/ /usr/share/nginx/html/
# The shared design system: the page links /design/index.css. Fonts and a
# logo put in design/ come along.
COPY design/ /usr/share/nginx/html/design/
# Build files and the company profile are not part of the public site.
RUN rm /usr/share/nginx/html/Dockerfile /usr/share/nginx/html/compose.yml \
       /usr/share/nginx/html/design/company.yaml /usr/share/nginx/html/design/README.md
