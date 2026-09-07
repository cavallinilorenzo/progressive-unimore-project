---
status: accepted
---

# Custom user model invece di Profile in OneToOne

`Progressive` definisce `AUTH_USER_MODEL` su un modello utente proprio, che porta direttamente i campi del dominio (`body_mass_kg`), invece di affiancare a `django.contrib.auth.User` un `Profile` collegato in OneToOne. È la strada raccomandata dalla documentazione ufficiale di Django, che invita a decidere al primo giorno perché cambiare idea dopo è costoso.

È una **deviazione consapevole dal progetto d'esempio del corso**, che usa `django.contrib.auth` liscio, e quindi dalla regola generale di questo progetto («si adotta ciò che il prof usa»). La deviazione è stata accettata perché il costo è nullo se presa subito ed enorme se presa dopo, e perché dimostra di aver letto la documentazione oltre le slide.

## Consequences

Il modello `Profile` non esiste: `body_mass_kg` sta sull'utente. Essendo l'unica cosa del progetto che il corso non ha mai nominato, va saputa spiegare alla discussione orale.
