python train.py --dataroot data/sg3r_house/house_yellow_sky --name house_yellow_sky --only_weight --rank 50 --lr_rampdown_length 0.5 --lr_schedule karras --update_layers 13 --trainer color --pretrained_G pretrained/stylegan3-r-house-512x512.pkl --max_iter 2000 --lr 0.05 --batch_size 8 --evaluation_metrics trainproject,trainsample --lambda_l1_clr 8