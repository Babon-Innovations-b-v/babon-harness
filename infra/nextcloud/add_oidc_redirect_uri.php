<?php
// Add redirect URIs to an existing Nextcloud oidc client, idempotently.
//
// The oidc app's occ commands can create and list clients but not add a
// redirect URI to one that exists, so this talks to the app's own data
// mappers. Run inside the Nextcloud container as www-data:
//
//   php add_oidc_redirect_uri.php <client-name> <uri> [<uri> ...]
//
// oidc-setup.sh copies it in and runs it for every SSO subdomain. A URI
// that is already registered is left alone.
require_once '/var/www/html/lib/base.php';
\OC::$CLI = true;

$wantClient = $argv[1];
$wantUris = array_slice($argv, 2);

$clientMapper = \OC::$server->get(\OCA\OIDCIdentityProvider\Db\ClientMapper::class);
$uriMapper    = \OC::$server->get(\OCA\OIDCIdentityProvider\Db\RedirectUriMapper::class);

$client = null;
foreach ($clientMapper->getClients() as $candidate) {
    if ($candidate->getName() === $wantClient) {
        $client = $candidate;
        break;
    }
}
if (!$client) {
    fwrite(STDERR, "client '$wantClient' not found\n");
    exit(1);
}

$existing = $uriMapper->getByClientId($client->getId());
$haveUris = array_map(fn($r) => $r->getRedirectUri(), $existing);

$added = 0;
foreach ($wantUris as $uri) {
    if (in_array($uri, $haveUris, true)) {
        echo "  exists: $uri\n";
        continue;
    }
    $row = new \OCA\OIDCIdentityProvider\Db\RedirectUri();
    $row->setClientId($client->getId());
    $row->setRedirectUri($uri);
    $uriMapper->insert($row);
    echo "  +     $uri\n";
    $added++;
}
echo "{$client->getName()} ({$client->getId()}): added $added\n";
