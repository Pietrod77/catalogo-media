on percorsoProgetto()
	set percorsoApp to POSIX path of (path to me)
	set percorsoProgetto to do shell script "dirname " & quoted form of percorsoApp
	return percorsoProgetto
end percorsoProgetto

on open theItems
	set radice to percorsoProgetto()
	repeat with anItem in theItems
		set inputPath to POSIX path of anItem
		if inputPath ends with "/" then set inputPath to text 1 thru -2 of inputPath
		set outputPath to inputPath & "_rinominato"
		try
			set risultato to do shell script "cd " & quoted form of radice & " && venv/bin/python scripts/rinomina_batch.py " & quoted form of inputPath & " " & quoted form of outputPath
			display dialog "Fatto! Risultati in:" & return & outputPath & return & return & risultato buttons {"OK"} default button "OK"
		on error errMsg
			display dialog "Errore durante la rinomina:" & return & errMsg buttons {"OK"} default button "OK" with icon stop
		end try
	end repeat
end open

on run
	display dialog "Trascina una cartella di foto sopra questa app per rinominarle in base al riconoscimento volti." buttons {"OK"} default button "OK"
end run
