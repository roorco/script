#!/usr/bin/env fish
# Impedisci lo standby all'avvio dello script
systemd-inhibit --what=idle --who="Toggle Audio Script" --why="Gestione radio programmata" --mode=block fish -c '
# Avvia mpv in background all inizio
mpv --no-video --volume=100 "http://icecast.radiofrance.fr/francemusique-hifi.aac" &
set mpv_pid $last_pid
echo "France Musique avviata (PID: $mpv_pid) - $(date)"

while true
    # Controlla se è ora di fermarsi (19:00 o dopo)
    set current_hour (date +%H)
    if test $current_hour -ge 19
        echo "Sono le 19:00 o dopo - Script terminato - $(date)"
        pactl set-sink-mute @DEFAULT_SINK@ 0  # Assicura che l audio sia attivo prima di uscire
        kill $mpv_pid 2>/dev/null  # Ferma mpv
        break
    end
    
    # Ripristina l audio (radio attiva)
    pactl set-sink-mute @DEFAULT_SINK@ 0
    echo "Audio attivo (radio) - $(date)"
    sleep 2h
    
    # Controlla di nuovo prima di mutare
    set current_hour (date +%H)
    if test $current_hour -ge 19
        echo "Sono le 19:00 o dopo - Script terminato - $(date)"
        pactl set-sink-mute @DEFAULT_SINK@ 0
        kill $mpv_pid 2>/dev/null  # Ferma mpv
        break
    end
    
    # Muta l audio
    pactl set-sink-mute @DEFAULT_SINK@ 1
    echo "Audio mutato - $(date)"
    sleep 1h
end
' && systemctl suspend
