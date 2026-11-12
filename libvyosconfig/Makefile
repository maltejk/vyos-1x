BUILDDIR=_build
VPATH=$(BUILDDIR)
OCAMLDIR=$(shell eval $$(opam env --root=/opt/opam); ocamlc -where)
$(shell mkdir -p $(BUILDDIR) $(BUILDDIR)/stub $(BUILDDIR)/lib $(BUILDDIR)/stub_generator $(BUILDDIR)/test $(BUILDDIR)/generated)
PACKAGES=vyos1x-config,re,ctypes.stubs,ctypes.foreign

GENERATOR_FILES=$(BUILDDIR)/lib/bindings.cmo \
                $(BUILDDIR)/stub_generator/generate.cmo

LIBFILES=$(BUILDDIR)/lib/bindings.cmo \
         $(BUILDDIR)/generated/vyosconfig_bindings.cmo  \
         $(BUILDDIR)/lib/apply_bindings.cmo  \
         $(BUILDDIR)/generated/vyosconfig.o

CAML_INIT=$(BUILDDIR)/stub/init.o
CAML_CTYPES:=$(shell eval $$(opam env --root=/opt/opam); ocamlfind query ctypes)
CAML_STDLIB:=$(shell eval $$(opam env --root=/opt/opam); ocamlfind ocamlc -config | awk '/^standard_library_default:/ {print $$2}')

# The files that we'll generate
GENERATED=$(BUILDDIR)/generated/vyosconfig.h \
          $(BUILDDIR)/generated/vyosconfig.c \
          $(BUILDDIR)/generated/vyosconfig_bindings.ml

OSTYPE:=$(shell eval $$(opam env --root=/opt/opam); ocamlfind ocamlc -config | awk '/^os_type:/ {print $$2}')
SYSTEM:=$(shell eval $$(opam env --root=/opt/opam); ocamlfind ocamlc -config | awk '/^system:/ {print $$2}')
EXTDLL:=$(shell eval $$(opam env --root=/opt/opam); ocamlfind ocamlc -config | awk '/^ext_dll:/ {print $$2}')

CC:= $(shell eval $$(opam env --root=/opt/opam); ocamlfind ocamlc -config | awk '/^bytecomp_c_compiler/ {for(i=2;i<=NF;i++) printf "%s " ,$$i}')

LIBNAME:=libvyosconfig.so.0

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
	# SRX: ocamlc's `ld -r` (custom runtime link) has no default search path on
	# mips64el -- static libs must be visible in /usr/lib/ocaml.
	for l in ffi pcre2-8 pthread; do ln -sf /usr/lib/mips64el-linux-gnuabi64/lib$${l}.a /usr/lib/ocaml/lib$${l}.a; done
	eval $$(opam env --root=/opt/opam); ocamlfind ocamlc -custom -output-complete-obj -runtime-variant _pic -thread -linkpkg \
		-package $(PACKAGES),threads.posix \
		_build/stub/init.o _build/lib/bindings.cmo \
		_build/generated/vyosconfig_bindings.cmo _build/lib/apply_bindings.cmo \
		-o _build/vyosconfig_bc.o
	gcc -shared -o $@ -Wl,-soname,$(LIBNAME) _build/vyosconfig_bc.o \
		_build/generated/vyosconfig.o -lm -ldl
	strip --strip-unneeded $@
endif

stubs: $(GENERATED)

$(BUILDDIR)/stub/%.o:
	eval $$(opam env --root=/opt/opam); ocamlc -g -c stub/init.c
	mv init.o $@

$(GENERATED): $(GENERATOR)
	eval $$(opam env --root=/opt/opam); $(GENERATOR) $(BUILDDIR)/generated

$(BUILDDIR)/%.o: %.c
	$(CC) -c -o $@ -fPIC -I $(CAML_CTYPES) -I $(CAML_STDLIB) -I $(OCAMLDIR) -I $(OCAMLDIR)/../ctypes $<

$(BUILDDIR)/%.cmo: %.ml
	eval $$(opam env --root=/opt/opam); ocamlfind ocamlc -c -o $@ -I $(BUILDDIR)/generated -I $(BUILDDIR)/lib -thread -package $(PACKAGES) $<

$(GENERATOR): $(GENERATOR_FILES)
	eval $$(opam env --root=/opt/opam); ocamlfind ocamlc -o $@ -I $(BUILDDIR)/lib -linkpkg -thread -package $(PACKAGES) $^

install: sharedlib
	@mkdir -p /usr/lib
	@cp $(BUILDDIR)/libvyosconfig$(EXTDLL) /usr/lib/$(LIBNAME)

clean:
	rm -rf $(BUILDDIR)
