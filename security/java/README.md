# OpenJDK certificate mitigation — 22 October 2026

CVE-2026-91403 concerns compromised intermediate CA certificates. OpenJDK's
[21 October advisory](https://openjdk.org/groups/vulnerability/advisories/2026-10-21) recommends updating the JVM or replacing
`lib/security/blocked.certs`. This is the latter mitigation; it does not upgrade
Java or address unrelated JVM/OS vulnerabilities.

The Unix download at ops.java returned 403 during preparation. Instead, the
fixture and unmodified OpenJDK converter were obtained at the immutable upstream
commit `22bc7357ce6bc5f1ed2f1e83e0544b2c25f781d4`. `provenance.json` records both source URLs and
SHA-256 checksums. The official converter includes alternative DER encodings;
do not replace it with a simple certificate-byte hashing loop.

Generated file SHA-256: `2596bb6dda83c66d96c5a252d7b2ae1f24cc1ae3f1890223b4f3591a8d52bf10`.
The fixture contains 35 certificates and produces 86 unique fingerprints.
Old vendor files from all five production JVM services contain 38 fingerprints;
all are retained. The unmitigated host JVM failed the fixture (16 certificates
unblocked). After replacement, it rejects all 35. Disposables using the existing
Temurin 25 and Red Hat Keycloak 21 images also reject all 35 with this file.

## Runtime configuration

Compose mounts `blocked-2596bb6dda83c66d96c5a252d7b2ae1f24cc1ae3f1890223b4f3591a8d52bf10.certs` read-only at each JVM's security path. Missing host files
fail instead of creating directories. The content-addressed source filename is
intentional: a future blocklist update changes Compose's service configuration,
which recreates the JVM and remounts the new inode. A restart alone can retain an
old file bind mount, and an already running JVM can cache its old blocklist.
Ansible copies `security/` before Compose convergence. JVMs do not share a writable
security file. Keycloak uses the stable `/usr/lib/jvm/jre-21` symlink, verified in
its pinned image. The optional Jenkins build copies the same blocklist into its
base JVM before running its plugin installer.

`blocked.certs` is the identical build-time artifact for standalone Dockerfiles;
the versioned copy is the immutable Compose source. The backend, consumer and
model-mock source repositories also include the artifact in both JDK/JRE stages.
Their existing published image digests are unchanged; the Compose mount protects
the existing images without publishing replacement application releases.

## Verification and renewal

Run `python3 scripts/verify-java-security.py` and the normal Compose/pin checks.
Compile `BlockedCertificatesProbe.java` with `javac --release 17 -d /tmp/probe`,
then run `java --add-exports java.base/sun.security.util=ALL-UNNAMED -cp /tmp/probe
BlockedCertificatesProbe /path/to/blocked.certs.pem` against the JVM under test.
This performs offline JVM certificate lookup checks, not network exploitation.

To reproduce the artifact, download the converter and fixture from the manifest,
verify their hashes, compile the converter with
`--add-exports java.base/sun.security.util=ALL-UNNAMED`, and run
`build.tools.blockedcertsconverter.BlockedCertsConverter` with the fixture on stdin.
After upstream updates, preserve custom/vendor blocks, freeze new provenance,
regenerate both copies, change every Compose source to its new content hash,
and rerun JVM, profile and mutation checks before rollout. Do not silently weaken
the expected fingerprint or fixture counts. A vendor upgrade can remove this
override only after its own default blocklist passes the same tests.

Framework mutation scope is unchanged (no PIT/Stryker-selected application code
changed). Two frozen config mutants compiled and were killed: omitting the
sandbox mount and reverting production to an unversioned bind source. No survivors
or invalid candidates remain. Results are in
`experiments/llm-mutation/results/java-security-2026-10-22.json`.
