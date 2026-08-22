# One binary for everyone

Every customer gets the same executable, byte for byte. It is not built per order, it
carries no customer's address, and it checks no licence. This note records why, because
the opposite is a reasonable-sounding idea that keeps coming back.

## What a per-customer build would be for

The worry it answers is reuse: a customer pays for one wallet, then runs the program for
their friend's wallet, or passes it on. Compiling their address into the binary and
refusing any config that does not match would stop that.

## Why it is not done

**There is nothing to protect.** The executable is a search engine with a text file for
input. The thing being sold is the web-side work — the memory interview, the grammar it
produces, the ordering that tries likely passphrases first. Anyone who wanted to avoid
paying would not crack our binary; they would download upstream *btcrecover*, which is
free, public, and can do the same search. Locking the exe guards a door in a field.

**The licence does not allow it to work.** This is GPLv2 software. The complete
corresponding source ships with the binary, and the recipient is entitled to modify and
redistribute it. Whatever check is compiled in, they may lawfully remove — and given the
source, in minutes. A lock that the licence obliges us to hand over the key to is theatre.

**It destroys the only proof we have.** One published hash is worth something because
*everyone receives the same file*. Ten customers can compare their downloads with each
other and with the hash in the release, and a difference would be visible. Per-customer
builds end that: each hash is unique, there is nothing to compare against, and "here is
the hash of your build" only says that we know what we sent. The customer is asked to
trust the same party they were trying to check.

**It would publish a list of people who lost access to their wallets.** A per-customer
build needs the address as a build input. Built in the open — which is the only way it
could be verified at all — the workflow log ties a bitcoin address to *someone who paid a
recovery service because they cannot get into it*. The address is public; that association
is not, and it names a wallet whose owner is locked out. It also hands a customer list to
anyone who looks. This is worse than the problem being solved.

**It costs turnaround and signing.** Every order waits for a build, and every unique
binary needs its own signature or it trips SmartScreen on first run. One signed reference
binary accumulates reputation; a thousand one-off binaries never do.

## What the exe already does

It refuses to run without an address in the config (`btcrecover/embed.py`) — there is
nothing to recognise the right passphrase by. So the search is already bound to an
address. The only thing a compiled-in address would add is stopping the customer from
editing that field in their own JSON file, which takes a text editor and five seconds.

## The middle path, if it is ever wanted

The exe stays identical, and a small file signed by us — address and order number, no
passphrase data — is issued alongside. The exe checks the signature. This keeps one hash,
publishes nothing, and needs no per-order build. It is still removable under the GPL, so
it deters casual reuse rather than preventing it. The cost is that we would have to know
the customer's address, which today never leaves their browser.

Not built. Recorded here so the option is not re-derived from scratch.

## What actually protects the business

The service, not the binary: the interview that turns a vague memory into a search worth
running, the ordering that reaches the answer sooner, and the contract. None of that
travels with a copied exe.
