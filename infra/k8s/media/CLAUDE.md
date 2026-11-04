# infra/k8s/media/

The namespace video calls and recording move into in a later piece, with the vault Secret `harness-env`. Today they run on the media box from `infra/media/`; its overlay has the rules.

- Media pods select the `media` pool role. Its public address is zonal, so the role keeps to its own zone set (`POOL_MEDIA_ZONES`) and its fallbacks join the preferred pool's security group.
