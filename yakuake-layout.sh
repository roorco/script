#!/usr/bin/env bash
# Apre quattro schede in Yakuake: posta, calendario, file, terminale
Q="qdbus org.kde.yakuake"

lancia() {            # $1 = id sessione, $2 = comando
  TID=$($Q /yakuake/sessions org.kde.yakuake.terminalIdsForSessionId "$1")
  TID=${TID%%,*}      # se ci sono piu' terminali, prende il primo
  sleep 0.5
  $Q /yakuake/sessions org.kde.yakuake.runCommandInTerminal "$TID" "$2"
}

# la scheda gia' aperta all'avvio diventa "posta"
ID=$($Q /yakuake/sessions org.kde.yakuake.activeSessionId)
$Q /yakuake/tabs org.kde.yakuake.setTabTitle "$ID" "posta"
lancia "$ID" "neomutt"

aggiungi() {          # $1 = titolo, $2 = comando (vuoto = solo terminale)
  SID=$($Q /yakuake/sessions org.kde.yakuake.addSession)
  sleep 0.5
  $Q /yakuake/tabs org.kde.yakuake.setTabTitle "$SID" "$1"
  [ -n "$2" ] && lancia "$SID" "$2"
}

aggiungi "calendario" "ikhal"
aggiungi "yazi" "yazi"
aggiungi "terminale" ""
