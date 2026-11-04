echo "Functions in desktop_scripts.html but not in app.js:"
cat desktop_funcs_sorted.txt | comm -23 - app_funcs_sorted.txt | wc -l
echo "Functions in app.js but not in desktop_scripts.html:"
cat app_funcs_sorted.txt | comm -13 desktop_funcs_sorted.txt - | wc -l
echo "Functions in desktop_scripts.html but not in scripts.html:"
cat desktop_funcs_sorted.txt | comm -23 - web_funcs_sorted.txt | wc -l
echo "Functions in scripts.html but not in desktop_scripts.html:"
cat web_funcs_sorted.txt | comm -13 desktop_funcs_sorted.txt - | wc -l
