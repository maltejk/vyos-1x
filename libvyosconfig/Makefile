BUILDDIR=_build
# SRX cross build: XTOOLCHAIN=mips64el selects the findlib toolchain
# of the xcross image (/opt/xocaml, docker/xcross/xocaml-setup.sh), see `cross`
OCAMLFIND=ocamlfind$(if $(XTOOLCHAIN), -toolchain $(XTOOLCHAIN))
VPATH=$(BUILDDIR)
OCAMLDIR=$(shell eval $$(opam env --root=/opt/opam); $(OCAMLFIND) ocamlc -where)
$(shell mkdir -p $(BUILDDIR) $(BUILDDIR)/stub $(BUILDDIR)/lib $(BUILDDIR)/stub_generator $(BUILDDIR)/test $(BUILDDIR)/generated)
PACKAGES=vyos1x-config,re,ctypes.stubs,ctypes.foreign

GENERATOR_FILES=$(BUILDDIR)/lib/bindings.cmo \
                $(BUILDDIR)/stub_generator/generate.cmo

LIBFILES=$(BUILDDIR)/lib/bindings.cmo \
         $(BUILDDIR)/generated/vyosconfig_bindings.cmo  \
         $(BUILDDIR)/lib/apply_bindings.cmo  \
         $(BUILDDIR)/generated/vyosconfig.o

CAML_INIT=$(BUILDDIR)/stub/init.o
CAML_CTYPES:=$(shell eval $$(opam env --root=/opt/opam); $(OCAMLFIND) query ctypes)
CAML_STDLIB:=$(shell eval $$(opam env --root=/opt/opam); $(OCAMLFIND) ocamlc -config | awk '/^standard_library:/ {print $$2}')

# The files that we'll generate
GENERATED=$(BUILDDIR)/generated/vyosconfig.h \
          $(BUILDDIR)/generated/vyosconfig.c \
          $(BUILDDIR)/generated/vyosconfig_bindings.ml

OSTYPE:=$(shell eval $$(opam env --root=/opt/opam); $(OCAMLFIND) ocamlc -config | awk '/^os_type:/ {print $$2}')
SYSTEM:=$(shell eval $$(opam env --root=/opt/opam); $(OCAMLFIND) ocamlc -config | awk '/^system:/ {print $$2}')
EXTDLL:=$(shell eval $$(opam env --root=/opt/opam); $(OCAMLFIND) ocamlc -config | awk '/^ext_dll:/ {print $$2}')

CC:= $(shell eval $$(opam env --root=/opt/opam); $(OCAMLFIND) ocamlc -config | awk '/^bytecomp_c_compiler/ {for(i=2;i<=NF;i++) printf "%s " ,$$i}')

LIBNAME:=libvyosconfig.so.0
MULTIARCH:=$(shell $(firstword $(CC)) -print-multiarch)

ifeq ($(OSTYPE),$(filter $(OSTYPE),Win32 Cygwin))
EXTEXE=.exe
else
EXTEXE=
endif

GENERATOR=$(BUILDDIR)/generate$(EXTEXE)

all: sharedlib

PHONY: depends
depends:
	sudo sh -c 'eval $$(opam env --root=/opt/opam --set-root) ; sh ./srx-opam-compat.sh'

sharedlib: depends $(BUILDDIR)/libvyosconfig$(EXTDLL)

ifeq ($(OSTYPE),$(filter $(OSTYPE),Win32 Cygwin))
$(BUILDDIR)/libvyosconfig$(EXTDLL): $(CAML_INIT) $(LIBFILES)
	ocamlfind ocamlc -o $@ -linkpkg -output-obj -verbose -package $(PACKAGES) $^
else ifeq ($(SYSTEM),$(filter $(SYSTEM),macosx))
$(BUILDDIR)/libvyosconfig$(EXTDLL): $(CAML_INIT) $(LIBFILES)
	ocamlfind ocamlc -o $@ -linkpkg -runtime-variant _pic -verbose -ccopt -dynamiclib -package $(PACKAGES) $^
else
$(BUILDDIR)/libvyosconfig$(EXTDLL): $(CAML_INIT) $(LIBFILES)
	# SRX: no ocamlopt on mips64el, so we build bytecode-only. 'ocamlc -output-obj'
	# alone cannot emit a shared object; embed the runtime with -custom
	# -output-complete-obj, then link the result into a .so with gcc.
	# $(PACKAGES) excludes the vyconf packages (unusable in a shared lib) and
	# includes threads.posix which -thread maps to.
	# SRX: ocamlc's `ld -r` (custom runtime link) has no default search path:
	# -I adds the multiarch dir of the static libs (libffi, libpcre2-8) as -L.
	eval $$(opam env --root=/opt/opam); $(OCAMLFIND) ocamlc -custom -output-complete-obj -runtime-variant _pic -thread -linkpkg \
		-package $(PACKAGES),threads.posix -I /usr/lib/$(MULTIARCH) \
		$(BUILDDIR)/stub/init.o $(BUILDDIR)/lib/bindings.cmo \
		$(BUILDDIR)/generated/vyosconfig_bindings.cmo $(BUILDDIR)/lib/apply_bindings.cmo \
		-o $(BUILDDIR)/vyosconfig_bc.o
	$(CC) -shared -o $@ -Wl,-soname,$(LIBNAME) $(BUILDDIR)/vyosconfig_bc.o \
		$(BUILDDIR)/generated/vyosconfig.o -lm -ldl
	strip --strip-unneeded $@
endif

stubs: $(GENERATED)

$(BUILDDIR)/stub/%.o:
	eval $$(opam env --root=/opt/opam); $(OCAMLFIND) ocamlc -g -c stub/init.c
	mv init.o $@

$(GENERATED): $(GENERATOR)
	eval $$(opam env --root=/opt/opam); $(GENERATOR) $(BUILDDIR)/generated

$(BUILDDIR)/%.o: %.c
	$(CC) -c -o $@ -fPIC -I $(CAML_CTYPES) -I $(CAML_STDLIB) -I $(OCAMLDIR) -I $(OCAMLDIR)/../ctypes $<

$(BUILDDIR)/%.cmo: %.ml
	eval $$(opam env --root=/opt/opam); $(OCAMLFIND) ocamlc -c -o $@ -I $(BUILDDIR)/generated -I $(BUILDDIR)/lib -thread -package $(PACKAGES) $<

$(GENERATOR): $(GENERATOR_FILES)
	eval $$(opam env --root=/opt/opam); ocamlfind ocamlc -o $@ -I $(BUILDDIR)/lib -linkpkg -thread -package $(PACKAGES) $^

install: sharedlib
	@mkdir -p /usr/lib
	@cp $(BUILDDIR)/libvyosconfig$(EXTDLL) /usr/lib/$(LIBNAME)

# mips64el lib next to the build-arch one (which the build itself loads): same
# generated stubs, generator not rebuilt (it runs on the build arch)
X=_build-mips64el
cross:
	mkdir -p $(X)/generated && cp -a $(GENERATED) $(X)/generated/
	$(MAKE) XTOOLCHAIN=mips64el BUILDDIR=$(X) -o $(X)/generate $(X)/libvyosconfig$(EXTDLL)

clean:
	rm -rf $(BUILDDIR) _build-mips64el
