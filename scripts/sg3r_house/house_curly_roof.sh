python train.py --dataroot data/sg3r_house/house_curly_roof --pretrained_G pretrained/stylegan3-r-house-512x512.pkl --lambda_lpips 1 --lambda_l1 0 --lambda_mse 0 --lr_schedule karras --evaluation_metrics trainproject,valpixelerror,valchamfer,valsample --only_weight --batch_size 8 --lr 0.05 --max_iter 2000 --lr_rampdown_length 0.5 --rank 50 --update_layers 8 --random_sample_trunc 0.5 --name house_curly_roof
