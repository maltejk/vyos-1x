# SRX cross build: xcross image adds the mips64el (bytecode) context
XWS=$(if $(wildcard /opt/xocaml/dune-workspace),--workspace /opt/xocaml/dune-workspace)

all:
	eval $$(opam env --root=/opt/opam --set-root); dune build $(XWS)

clean:
	eval $$(opam env --root=/opt/opam --set-root); dune clean

.PHONY: all clean
