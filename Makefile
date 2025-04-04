build:
    sudo docker build -t event_organizer_bot_image .
logs:
    sudo docker logs event_organizer_bot_cont
images:
    sudo docker images

    sudo docker ps -a
run:
	sudo docker run -it -d --env-file .env --restart=unless-stopped --name event_organizer_bot_cont event_organizer_bot_image
stop:
	sudo docker stop event_organizer_bot_cont
attach:
	sudo docker attach event_organizer_bot_cont
delete:
	sudo docker rm event_organizer_bot_cont