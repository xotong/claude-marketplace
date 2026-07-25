

The following exmaple is a common way to use this component

```yaml
include: 
  - component: $CI_SERVER_FQDN/lobster-thermidor/devops/ci-catalogue/container-scanning/ container-scanning@~latest
    inputs:
      stage: scans
      language: javascript
      variant: openjdk17 # or openjdk21
```



How to set up gitlab's SCA
https://docs.gitlab.com/user/application_security/dependency_scanning/dependency_scanning_sbom/#offline-environment

How to bring in Gitlab SCA advisory database
https://docs.gitlab.com/topics/offline/quick_start_guide/#enabling-the-package-metadata-database

Run on internet machine
docker run --rm -it -v "$(pwd):/work" gcr.io/google.com/cloudsdktool/google-cloud-cli:stable gsutil -m rsync -r gs://prod-export-advisory-bucket-1a6c642fc4de57d4 /work/advisories/

Remove unsupported packages
sudo su

DIRS=(apk cargo cbl-mariner conan deb nuget packagist pub rpm wolfi rubygem); for dir in "${DIRS[@]}"; do rm -rf "advisories/v2/$dir"; done

Create tar ball of file
tar -czvf advisories.tar.gz -C advisories .

Bring it in to Air-Gap!

The following to be run in Air-Gap!

TOOLBOX_POD=$(oc get pods -n gitlab-system -l app=toolbox -o jsonpath='{.items[0].metadata.name}')
oc cp advisories.tar.gz $TOOLBOX_POD:/srv/gitlab/vendor/package_metadata/advisories && oc exec -n gitlab-system $TOOLBOX_POD -- tar -xzvf /srv/gitlab/vendor/package_metadata/advisories/advisories.tar.gz -m 2>/dev/null || true

# Error on cannot change mode is normal due to mounted volume permission above to surpress warning

for dir in advisories/v2/*; do
  [ -d "$dir" ] || continue
  count=$(
    find "$dir" -type f -name '*.ndjson' -print0 |
    xargs -0 python3 -c '
import sys, json
ids = set()
for fn in sys.argv[1:]:
    with open(fn) as f:
        for line in f:
            if line.strip():
                ids.add(json.loads(line)["advisory"]["id"])
print(len(ids))
'
  )
  printf "%-15s %d\n" "$(basename "$dir")" "$count"
done

PackageMetadata::SyncService.send(:remove_const, :MAX_LEASE_LENGTH)
PackageMetadata::SyncService.const_set(:MAX_LEASE_LENGTH, 60.minutes)

PackageMetadata::SyncService.send(:remove_const, :MAX_SYNC_DURATION)
PackageMetadata::SyncService.const_set(:MAX_SYNC_DURATION, 55.minutes)

prev=""

while true; do
  current=$(oc exec -n gitlab-system "$TOOLBOX_POD" -- \
    gitlab-rails runner \
    'puts PackageMetadata::Checkpoint.order(:purl_type).pluck(:purl_type,:sequence,:chunk).join("|")')

  if [ "$current" = "$prev" ]; then
    echo "No checkpoint progress detected. Sync appears complete."
    break
  fi

  prev="$current"

  oc exec -n gitlab-system "$TOOLBOX_POD" -- \
    gitlab-rails runner '
      PackageMetadata::SyncService.send(:remove_const, :MAX_LEASE_LENGTH)
      PackageMetadata::SyncService.const_set(:MAX_LEASE_LENGTH, 60.minutes)

      PackageMetadata::SyncService.send(:remove_const, :MAX_SYNC_DURATION)
      PackageMetadata::SyncService.const_set(:MAX_SYNC_DURATION, 55.minutes)

      PackageMetadata::AdvisoriesSyncWorker.new.perform
    '
done
