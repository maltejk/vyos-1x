#!/bin/sh
# SRX: vyos1x-config (pinned commit) uses OCaml 4.14 In_channel; the mips64el
# builder only has ocaml-system 4.13 (no ocamlopt on mips64). Pin vyos1x-config
# from a local source with the In_channel read replaced by 4.13-compatible
# channel reads, then pin vyconf as upstream does.
set -e
SRC=/tmp/vyos1x-config-src
rm -rf "$SRC"
git clone -q https://github.com/vyos/vyos1x-config.git "$SRC"
cd "$SRC"
git checkout -q a7967ec86ffa5d65ac3c4fa8e166845414aedd0a
patch -p1 <<'ENDCOMPAT'
--- a/src/completion.ml
+++ b/src/completion.ml
@@ -38,7 +38,14 @@ let get_completion_data (node: Reference_tree.t) =
 let execute_completion_script cmd =
     let () = Unix.putenv "vyos_completion_dir" "/usr/libexec/vyos/completion" in
     let chan = Unix.open_process_in cmd in
-    let out = In_channel.input_all chan in
+    let out =
+      let buf = Buffer.create 4096 and tmp = Bytes.create 4096 in
+      let rec go () =
+        let n = input chan tmp 0 (Bytes.length tmp) in
+        if n > 0 then (Buffer.add_subbytes buf tmp 0 n; go ()) in
+      go ();
+      Buffer.contents buf
+    in
     let result = Unix.close_process_in chan in
     match result with
     | Unix.WEXITED 0 -> out
ENDCOMPAT
# opam >= 2.1 (2.6.1 on the amd64 runner) pins the git HEAD commit and ignores
# working-tree edits, so commit the compat change before pinning.
git -c user.name=srx -c user.email=srx@localhost commit -qam srx-ocaml413-compat
opam pin add vyos1x-config "$SRC" -y
# /vyos-src is a read-only bind mount owned by the host user. opam >= 2.6 runs git
# with GIT_CONFIG_GLOBAL=/dev/null (no safe.directory possible) and git refuses a
# foreign-owned repository, so pin a root-owned copy (cp -r: no ownership kept).
VC=/tmp/vyconf-src
rm -rf "$VC"
cp -r /vyos-src/vyconf "$VC"
opam pin add vyconf "$VC" -y
# SRX cross build: the same source for the mips64el findlib toolchain
# of the xcross image (docker/xcross/xocaml-setup.sh); bytecode, C stub cross built
if [ -f /opt/xocaml/dune-workspace ]; then
    dune build --workspace /opt/xocaml/dune-workspace -p vyos1x-config \
        _build/default.mips64el/vyos1x-config-mips64el.install
    cp -aL _build/install/default.mips64el/lib/. /opt/xocaml/lib/
fi
