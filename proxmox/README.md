# proxmox

The Proxmox practices I actually use: unprivileged LXCs that run Docker, bind
mounts shared between containers with POSIX ACLs, and the VM settings that
fixed boot problems on my hardware. Notes and commands, no compose file.

## What

Two Proxmox hosts. Most services run as Docker containers on the main host or
inside small unprivileged LXCs (DNS, the VPN server, the code-server IDE).
A few things need a full VM (Home Assistant OS). One directory on the main
host is shared into several LXCs through bind mounts, and that sharing is
where most of the permission trouble came from.

## Why

- **Unprivileged LXCs.** Root inside the container maps to an unprivileged
  UID on the host (container UID + 100000), so a compromised container is not
  host root.
- **ACLs instead of 777.** Several containers need to write the same shared
  directory. A world-writable directory lets every process in every container
  write; an ACL grants exactly the mapped UIDs that need it.
- **Docker inside LXC** instead of a VM per service: containers share the
  host kernel, so a small service does not pay for a whole guest OS.

## Unprivileged LXC with Docker

Create the container unprivileged, and turn on nesting, which Docker inside
an LXC needs:

```bash
pct set 901 --features nesting=1
pct config 901 | grep -E '^(unprivileged|features)'
#   features: nesting=1
#   unprivileged: 1
```

Two things that bit me:

- **AppArmor and database containers.** On the Proxmox host's own Docker,
  database-backed containers (and one that needs `socketpair()`) need
  `security_opt: [apparmor:unconfined]`; the default Docker AppArmor profile
  blocks them. Treat it as a per-container fix
  when a container fails with permission errors on sockets or files it
  owns, not a default for everything.
- **`pct exec` from a remote, non-interactive session can lose stdout.** When
  a command's output matters, write it to a file inside the container and
  copy it out with `pct pull <id> /tmp/out.txt /tmp/out.txt`.

## Sharing a directory between LXCs

Bind mount the host directory into each container:

```bash
pct set 901 -mp0 /srv/shared,mp=/mnt/shared
```

Inside an unprivileged container, UID 1000 is UID 101000 on the host and
root is 100000. Grant those host UIDs write access with ACLs, and make it the
default for new files:

```bash
setfacl -Rm  u:101000:rwX,u:100000:rwX,m:rwx /srv/shared
setfacl -Rdm u:101000:rwX,u:100000:rwX,m:rwx /srv/shared
getfacl /srv/shared
```

The part that bites: **the ACL mask is the group permission bits.**
`chmod 600` on a file sets the mask to `---`, which silently caps every ACL
entry at nothing. `getfacl` still lists `user:101000:rwx`, but the
`#effective:---` column is the truth. So:

- For files that must stay private but still be readable by a mapped UID, use
  `0640` (mask `r--`), not `0600`.
- A directory created on the host with mode `2755` gets mask `r-x` for its
  new files; fix with `chmod g+w` on the host (from inside the container,
  even `sudo` gets EPERM).
- Test write access from inside the container, and check the mount is really
  there first (`mountpoint -q /mnt/shared`). A write "test" against an
  unmounted path writes to the empty directory under the mount point and
  passes.

## VM settings that matter on my hardware

```bash
qm create 902 --name vm-1 --memory 4096 --cores 2 \
  --cpu host --machine q35 --bios ovmf \
  --scsihw virtio-scsi-single --net0 virtio,bridge=vmbr0 --ostype l26
```

`--cpu host` is the one to remember. With the default `kvm64` CPU type, UEFI
guests on my mini PC failed to boot or had network trouble; `host` passes the
real CPU features through and fixed it. Check the CPU type first when a VM
will not boot, before looking at disks or network.

## Files

| File | Purpose |
|------|---------|
| `README.md` | These notes |

Not tested in this repository: these are commands from my notes, not a
script that was run for this folder.

## Integration

- **Backups**, back up the shared directory and each LXC with your backup
  tool (see `kopia`), and keep hypervisor-level backups for the VMs.
- **Access**, the hypervisors are Teleport nodes like everything else (see
  `teleport`), and the Proxmox web UI is LAN-only behind the proxy.
